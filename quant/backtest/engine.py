"""
backtest/engine.py — Walk-forward backtesting framework.

Methodology:
  - Walk-forward: train on 60 days, test on 30 days, roll forward.
  - Applies full strategy pipeline (indicators → regime → signal → score → risk)
    on historical data bar-by-bar.
  - XGBoost model is trained on the training window and evaluated on the test window.
  - Reports: win rate, avg R-multiple, max drawdown, Sharpe ratio, trade count.

Usage:
  python main.py --mode backtest --symbol BTCUSDT
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg
from features import indicators as ind
from regime import detector as regime_det
from signals import trend as trend_sig, mean_reversion as mr_sig, scorer
from risk import manager as risk_mgr

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    entry_idx: int
    exit_idx: int
    direction: str
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    strategy: str
    score: int
    ml_prob: float

    @property
    def pnl_pct(self) -> float:
        mult = 1 if self.direction == 'BUY' else -1
        return mult * (self.exit_price - self.entry_price) / self.entry_price

    @property
    def r_multiple(self) -> float:
        risk = abs(self.entry_price - self.stop_loss)
        if risk == 0:
            return 0.0
        return (self.exit_price - self.entry_price) / risk if self.direction == 'BUY' \
               else (self.entry_price - self.exit_price) / risk


@dataclass
class BacktestResult:
    symbol: str
    period_start: str
    period_end: str
    total_trades: int = 0
    winning_trades: int = 0
    win_rate: float = 0.0
    avg_r_multiple: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0
    total_return: float = 0.0
    trades: list[Trade] = field(default_factory=list)

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"  BACKTEST RESULTS: {self.symbol}")
        print(f"  Period: {self.period_start} → {self.period_end}")
        print(f"{'='*60}")
        print(f"  Trades:        {self.total_trades}")
        print(f"  Win Rate:      {self.win_rate:.1%}")
        print(f"  Avg R-Multi:   {self.avg_r_multiple:+.2f}R")
        print(f"  Total Return:  {self.total_return:+.2%}")
        print(f"  Max Drawdown:  {self.max_drawdown:.2%}")
        print(f"  Sharpe Ratio:  {self.sharpe:.2f}")
        print(f"{'='*60}\n")


def _simulate_trades(df: pd.DataFrame,
                     ml_predict_fn=None,
                     score_threshold: int = cfg.SCORE_THRESHOLD,
                     ml_threshold: float = cfg.ML_PROB_THRESHOLD) -> list[Trade]:
    """
    Simulate all trades on a historical OHLCV DataFrame.

    For each bar:
    1. Compute indicators.
    2. Detect regime.
    3. Generate signal (trend or mean-reversion).
    4. Score the signal.
    5. Check ML gate.
    6. If all gates pass, enter trade; exit at SL/TP or end of window.
    """
    df = ind.compute_all(df)
    df = df.dropna()
    trades: list[Trade] = []
    in_trade = False
    trade_entry_idx = 0
    trade_entry_price = 0.0
    trade_sl = 0.0
    trade_tp = 0.0
    trade_dir = ''
    trade_strategy = ''
    trade_score = 0
    trade_ml = 0.0

    for i in range(20, len(df) - cfg.ML_FORWARD_PERIODS):
        row = df.iloc[i]

        if in_trade:
            price = float(row['close'])
            if trade_dir == 'BUY':
                if price <= trade_sl or price >= trade_tp:
                    trades.append(Trade(
                        entry_idx=trade_entry_idx, exit_idx=i,
                        direction=trade_dir, entry_price=trade_entry_price,
                        exit_price=price, stop_loss=trade_sl, take_profit=trade_tp,
                        strategy=trade_strategy, score=trade_score, ml_prob=trade_ml,
                    ))
                    in_trade = False
            elif trade_dir == 'SELL':
                if price >= trade_sl or price <= trade_tp:
                    trades.append(Trade(
                        entry_idx=trade_entry_idx, exit_idx=i,
                        direction=trade_dir, entry_price=trade_entry_price,
                        exit_price=price, stop_loss=trade_sl, take_profit=trade_tp,
                        strategy=trade_strategy, score=trade_score, ml_prob=trade_ml,
                    ))
                    in_trade = False
            continue

        # Build a mock FeatureSet from current bar
        fs = _row_to_fs(df, i)

        # Regime gate
        regime = regime_det.detect(fs)
        if regime == 'UNCERTAIN':
            continue

        # Try trend signal in TRENDING regime
        signal = None
        if regime == 'TRENDING':
            signal = trend_sig.generate(fs)
        elif regime == 'RANGING':
            signal = mr_sig.generate(fs)

        if signal is None or not signal.is_actionable:
            continue

        # Risk levels
        rl = risk_mgr.compute_levels(fs.close, fs.atr, signal.direction)

        # Score gate
        s = scorer.score(fs, signal, rl.stop_loss, rl.take_profit)
        if s < score_threshold:
            continue

        # ML gate
        ml_prob = 0.5
        if ml_predict_fn:
            vec = fs.to_ml_vector()
            ml_prob = ml_predict_fn(vec)
        if ml_prob < ml_threshold:
            continue

        # Enter trade
        in_trade = True
        trade_entry_idx   = i
        trade_entry_price = fs.close
        trade_sl          = rl.stop_loss
        trade_tp          = rl.take_profit
        trade_dir         = signal.direction
        trade_strategy    = signal.strategy
        trade_score       = s
        trade_ml          = ml_prob

    # Force-close any open trade at end of window
    if in_trade and len(df) > trade_entry_idx:
        exit_price = float(df['close'].iloc[-1])
        trades.append(Trade(
            entry_idx=trade_entry_idx, exit_idx=len(df)-1,
            direction=trade_dir, entry_price=trade_entry_price,
            exit_price=exit_price, stop_loss=trade_sl, take_profit=trade_tp,
            strategy=trade_strategy, score=trade_score, ml_prob=trade_ml,
        ))

    return trades


def _row_to_fs(df: pd.DataFrame, i: int):
    """Build a lightweight FeatureSet from a historical bar (no external data)."""
    from features.multi_timeframe import FeatureSet
    row = df.iloc[i]

    # HTF trend: use last 12 bars of the same dataframe as a proxy
    htf_slice = df.iloc[max(0, i-12):i]
    if len(htf_slice) >= 5:
        htf_roc = float((htf_slice['close'].iloc[-1] - htf_slice['close'].iloc[0]) / htf_slice['close'].iloc[0])
        htf_trend = 'up' if htf_roc > 0.005 else ('down' if htf_roc < -0.005 else 'neutral')
    else:
        htf_roc, htf_trend = 0.0, 'neutral'

    return FeatureSet(
        symbol='BACKTEST',
        close=float(row['close']),
        open_=float(row['open']),
        high=float(row['high']),
        low=float(row['low']),
        volume=float(row['volume']),
        vwap=float(row.get('vwap', row['close'])),
        vwap_dist=float(row.get('vwap_dist', 0.0)),
        ewma_short=float(row.get('ewma_short', row['close'])),
        ewma_long=float(row.get('ewma_long',  row['close'])),
        ewma_diff=float(row.get('ewma_diff', 0.0)),
        atr=float(row.get('atr', row['close'] * 0.01)),
        atr_pct=float(row.get('atr_pct', 0.01)),
        bb_upper=float(row.get('bb_upper', row['close'] * 1.02)),
        bb_lower=float(row.get('bb_lower', row['close'] * 0.98)),
        bb_mid=float(row.get('bb_mid',   row['close'])),
        bb_pct=float(row.get('bb_pct',   0.5)),
        roc=float(row.get('roc', 0.0)),
        rsi=float(row.get('rsi', 50.0)),
        hh=bool(row.get('hh', False)),
        ll=bool(row.get('ll', False)),
        trend_score=int(row.get('trend_score', 0)),
        htf_trend=htf_trend,
        htf_roc=htf_roc,
        btc_corr=0.5,
        ob_imbalance=0.0,
        funding_rate=0.0,
        oi_current=0.0,
        oi_prev=0.0,
        oi_change_pct=0.0,
    )


def _compute_metrics(trades: list[Trade]) -> dict:
    if not trades:
        return dict(total=0, wins=0, win_rate=0, avg_r=0, max_dd=0, sharpe=0, total_ret=0)

    pnls = [t.pnl_pct for t in trades]
    r_mults = [t.r_multiple for t in trades]
    wins = [p for p in pnls if p > 0]

    # Equity curve for drawdown & Sharpe
    equity = np.cumprod([1 + p for p in pnls])
    running_max = np.maximum.accumulate(equity)
    drawdowns = (equity - running_max) / running_max
    max_dd = abs(drawdowns.min()) if len(drawdowns) > 0 else 0

    total_ret = equity[-1] - 1 if len(equity) > 0 else 0

    # Sharpe (annualized, assume 5m bars → ~105,120 per year / trades_per_year)
    if len(pnls) > 1:
        sharpe = np.mean(pnls) / (np.std(pnls) + 1e-9) * np.sqrt(252)
    else:
        sharpe = 0

    return dict(
        total=len(trades),
        wins=len(wins),
        win_rate=len(wins) / len(trades) if trades else 0,
        avg_r=float(np.mean(r_mults)) if r_mults else 0,
        max_dd=float(max_dd),
        sharpe=float(sharpe),
        total_ret=float(total_ret),
    )


def run(symbol: str,
        df: pd.DataFrame,
        train_days: int = 60,
        test_days: int = 30) -> list[BacktestResult]:
    """
    Walk-forward backtest across the full history in df.

    Parameters
    ----------
    symbol     : asset symbol
    df         : full historical OHLCV DataFrame (hourly preferred)
    train_days : training window length
    test_days  : test window length

    Returns
    -------
    List of BacktestResult per walk-forward window.
    """
    from models import xgboost_filter as xgb

    bars_per_day = 24   # assuming 1h bars
    train_bars = train_days * bars_per_day
    test_bars  = test_days  * bars_per_day

    results: list[BacktestResult] = []
    start = 0

    while start + train_bars + test_bars <= len(df):
        train_df = df.iloc[start : start + train_bars]
        test_df  = df.iloc[start + train_bars : start + train_bars + test_bars]

        # Train XGBoost on this window
        ml_ok = xgb.train(symbol, train_df)

        def ml_fn(vec):
            return xgb.predict(symbol, vec) if ml_ok else 0.5

        trades = _simulate_trades(test_df, ml_predict_fn=ml_fn)
        m = _compute_metrics(trades)

        result = BacktestResult(
            symbol=symbol,
            period_start=str(test_df.index[0].date()),
            period_end=str(test_df.index[-1].date()),
            total_trades=m['total'],
            winning_trades=m['wins'],
            win_rate=m['win_rate'],
            avg_r_multiple=m['avg_r'],
            max_drawdown=m['max_dd'],
            sharpe=m['sharpe'],
            total_return=m['total_ret'],
            trades=trades,
        )
        results.append(result)
        result.print_summary()

        start += test_bars

    if not results:
        logger.warning("Not enough data for walk-forward backtest (need %d bars)", train_bars + test_bars)

    return results
