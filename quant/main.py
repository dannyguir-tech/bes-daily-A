"""
main.py — Entry point for the quantitative trading alert engine.

Usage:
  python main.py                            # live mode, all symbols
  python main.py --mode live                # live mode
  python main.py --mode backtest            # backtest all symbols
  python main.py --mode backtest --symbol BTCUSDT   # backtest one symbol

Modes:
  live      Runs on LIVE_INTERVAL_SECS schedule (default 5 min).
            Fetches live data, computes signals, emits BUY/SELL/NO TRADE alerts.
  backtest  Fetches 90d of historical data, runs walk-forward backtest, prints results.
"""

import argparse
import logging
import sys
import os
import time

# ── Ensure quant/ is importable from anywhere ─────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))

import config as cfg
import db
from alerts import emitter
from data import fetcher, normalizer, orderbook
from features import multi_timeframe as mtf
from regime import detector as regime_det
from signals import trend as trend_sig, mean_reversion as mr_sig, scorer
from models import xgboost_filter as xgb, ensemble
from risk import manager as risk_mgr

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S',
)
logger = logging.getLogger('quant.main')


# ─── In-memory OI history for change tracking ─────────────────────────────────
_oi_prev: dict[str, float] = {}


# ─── Per-symbol live run ───────────────────────────────────────────────────────

def run_symbol(symbol: str, signal_tf: str = None) -> None:
    """
    Full pipeline for one symbol on one signal timeframe:
      1. Fetch OHLCV for the signal TF + its HTF from all exchanges
      2. Compute median price + OBI + OI + funding rate
      3. Build FeatureSet
      4. Detect regime
      5. Generate signal (trend or mean-reversion based on regime)
      6. Compute risk levels (ATR stop/TP)
      7. Score the signal
      8. ML probability filter
      9. Ensemble decision
      10. Emit alert (stdout + SQLite)
    """
    if signal_tf is None:
        signal_tf = cfg.PRIMARY_TF
    htf = cfg.HTF_MAP.get(signal_tf, cfg.HTF)
    fetch_tfs = list(dict.fromkeys([signal_tf, htf]))  # deduplicated, ordered

    try:
        # ── 1. OHLCV data ──────────────────────────────────────────────────
        frames: dict[str, 'pd.DataFrame'] = {}
        current_median_price = 0.0
        current_exchange_prices = {}
        for tf in fetch_tfs:
            exchange_dfs = fetcher.fetch_ohlcv_all_exchanges(symbol, tf)
            if not exchange_dfs:
                logger.warning("%s: no OHLCV data for %s", symbol, tf)
                continue
            med_price, ex_prices = normalizer.compute_median_price(exchange_dfs)
            df_norm = normalizer.normalize_all(exchange_dfs, tf)
            frames[tf] = df_norm
            if tf == signal_tf:
                current_median_price = med_price
                current_exchange_prices = ex_prices

        if signal_tf not in frames or frames[signal_tf] is None:
            logger.warning("%s: missing %s data, skipping", symbol, signal_tf)
            return

        frames = normalizer.align_to_primary(frames, primary=signal_tf)

        # ── 2. Microstructure data ─────────────────────────────────────────
        obi          = orderbook.get_obi(symbol)
        funding_rate = fetcher.fetch_funding_rate(symbol) or 0.0
        oi_current   = fetcher.fetch_open_interest(symbol) or 0.0
        oi_prev      = _oi_prev.get(symbol, oi_current)
        _oi_prev[symbol] = oi_current

        # ── 3. BTC frames for correlation (skip if this IS BTC) ────────────
        btc_frames = None
        if symbol != 'BTCUSDT' and 'BTCUSDT' in cfg.SYMBOLS:
            btc_frames = {}
            for tf in fetch_tfs:
                btc_df = fetcher.fetch_binance_ohlcv('BTCUSDT', tf)
                if btc_df is not None:
                    btc_frames[tf] = btc_df

        # ── 4. Feature set ─────────────────────────────────────────────────
        fs = mtf.build_feature_set(
            symbol=symbol,
            frames=frames,
            btc_frames=btc_frames,
            oi_current=oi_current,
            oi_prev=oi_prev,
            funding_rate=funding_rate,
            ob_imbalance=obi,
            median_price=current_median_price,
            exchange_prices=current_exchange_prices,
            primary_tf=signal_tf,
            htf=htf,
        )

        # ── 5. Regime ──────────────────────────────────────────────────────
        regime = regime_det.detect(fs)

        # ── 6. Signal generation ───────────────────────────────────────────
        if regime == 'TRENDING':
            signal = trend_sig.generate(fs)
        elif regime == 'RANGING':
            signal = mr_sig.generate(fs)
        else:
            emitter.emit_no_trade(symbol, "regime=UNCERTAIN", regime, timeframe=signal_tf)
            return

        # ── 7. Risk levels (needed for scoring) ───────────────────────────
        rl = risk_mgr.compute_levels(fs.close, fs.atr, signal.direction)

        # ── 8. Score ───────────────────────────────────────────────────────
        s = scorer.score(fs, signal, rl.stop_loss, rl.take_profit)
        bd = scorer.score_breakdown(fs, signal, rl.stop_loss, rl.take_profit)

        # ── 9. ML filter ──────────────────────────────────────────────────
        ml_prob = xgb.predict(symbol, fs.to_ml_vector())

        # ── 10. Ensemble decision ─────────────────────────────────────────
        decision = ensemble.decide(
            signal=signal,
            score=s,
            score_bd=bd,
            ml_prob=ml_prob,
            fs=fs,
            stop_loss=rl.stop_loss,
            take_profit=rl.take_profit,
            kelly_fraction=rl.kelly_fraction,
            regime=regime,
        )

        # ── 11. Emit ──────────────────────────────────────────────────────
        if decision.is_trade:
            emitter.emit_decision(symbol, decision, timeframe=signal_tf)
        else:
            emitter.emit_no_trade(symbol, decision.reject_reason, regime, timeframe=signal_tf)

    except Exception as exc:
        emitter.emit_error(f"run_symbol({symbol}, {signal_tf})", exc)
        logger.exception("Unhandled error in run_symbol(%s, %s)", symbol, signal_tf)


# ─── Bootstrap: train ML models before first live run ─────────────────────────

def bootstrap_models(symbols: list[str]) -> None:
    """Fetch historical data and train XGBoost models if not already saved."""
    emitter.emit_info(f"Bootstrapping ML models for {symbols}...")
    for symbol in symbols:
        try:
            df = fetcher.fetch_bootstrap_ohlcv(symbol, days=cfg.BOOTSTRAP_DAYS)
            if df is not None and len(df) > 100:
                xgb.maybe_retrain(symbol, df)
            else:
                logger.warning("Not enough bootstrap data for %s", symbol)
        except Exception as exc:
            logger.warning("Bootstrap failed for %s: %s", symbol, exc)


# ─── Live mode ────────────────────────────────────────────────────────────────

def live(symbols: list[str]) -> None:
    """
    Run the signal engine on a multi-timeframe schedule.
    Each signal timeframe runs on its own cadence (5m every 5 min, 1h every hour, etc.).
    The main loop ticks every 60 seconds and checks which TFs are due.
    """
    db.init_db()

    emitter.emit_info(
        f"Quant engine starting — symbols={symbols}, "
        f"timeframes={cfg.SIGNAL_TIMEFRAMES}, "
        f"score_threshold={cfg.SCORE_THRESHOLD}, "
        f"ml_threshold={cfg.ML_PROB_THRESHOLD}"
    )

    bootstrap_models(symbols)

    # Track last run time per timeframe
    last_run: dict[str, float] = {}
    tick_interval = 60  # check every 60 seconds

    while True:
        tick_start = time.time()
        now = tick_start

        for signal_tf in cfg.SIGNAL_TIMEFRAMES:
            interval_secs = cfg.TF_INTERVALS.get(signal_tf, 300)
            last = last_run.get(signal_tf, 0)

            if now - last >= interval_secs:
                emitter.emit_info(f"--- Tick [{signal_tf}] ({len(symbols)} symbols) ---")
                for symbol in symbols:
                    run_symbol(symbol, signal_tf=signal_tf)
                last_run[signal_tf] = now

        elapsed = time.time() - tick_start
        sleep_for = max(0, tick_interval - elapsed)
        logger.debug("Tick completed in %.1fs, sleeping %.1fs", elapsed, sleep_for)
        time.sleep(sleep_for)


# ─── Backtest mode ────────────────────────────────────────────────────────────

def backtest(symbols: list[str]) -> None:
    """Run walk-forward backtest for each symbol and print results."""
    from backtest import engine as bt_engine

    emitter.emit_info(f"Starting backtest for {symbols}...")
    for symbol in symbols:
        emitter.emit_info(f"Fetching {cfg.BOOTSTRAP_DAYS}d history for {symbol}...")
        df = fetcher.fetch_bootstrap_ohlcv(symbol, days=cfg.BOOTSTRAP_DAYS)
        if df is None or len(df) < 200:
            emitter.emit_info(f"  Skipping {symbol}: not enough historical data")
            continue
        bt_engine.run(symbol, df)


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Quantitative Trading Alert Engine')
    parser.add_argument('--mode',   choices=['live', 'backtest'], default='live',
                        help='Run mode (default: live)')
    parser.add_argument('--symbol', type=str, default=None,
                        help='Single symbol to run (default: all from QUANT_SYMBOLS)')
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else cfg.SYMBOLS

    if args.mode == 'backtest':
        backtest(symbols)
    else:
        live(symbols)


if __name__ == '__main__':
    main()
