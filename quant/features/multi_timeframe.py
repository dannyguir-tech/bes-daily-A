"""
features/multi_timeframe.py — Aligns features from 1m/5m/15m/1h into a unified
FeatureSet for the latest bar.

The primary timeframe (5m) drives signal generation. Higher timeframe (1h)
features are used for trend alignment. Lower timeframes provide noise context.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg
from features import indicators, correlation


@dataclass
class FeatureSet:
    """
    All features needed by the regime detector, signal generators, and scorer
    for a single asset at the latest bar.
    """
    symbol: str = ''

    # Price levels
    close: float = 0.0
    open_: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0

    # VWAP
    vwap: float = 0.0
    vwap_dist: float = 0.0      # (close - vwap) / vwap

    # EWMA
    ewma_short: float = 0.0
    ewma_long: float = 0.0
    ewma_diff: float = 0.0      # (short - long) / close

    # ATR
    atr: float = 0.0
    atr_pct: float = 0.0        # atr / close

    # Bollinger Bands
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_mid: float = 0.0
    bb_pct: float = 0.5         # 0=at lower, 1=at upper

    # Momentum
    roc: float = 0.0            # Rate of change (primary TF)
    rsi: float = 50.0

    # Trend structure
    hh: bool = False
    ll: bool = False
    trend_score: int = 0        # +1 HH, -1 LL, 0 neutral

    # HTF (1h) trend alignment
    htf_trend: str = 'neutral'  # 'up', 'down', 'neutral'
    htf_roc: float = 0.0

    # Correlation with BTC
    btc_corr: float = 0.5       # 0=inverse, 1=perfect correlation

    # OI & funding (from fetcher, injected externally)
    oi_current: float = 0.0
    oi_prev: float = 0.0
    oi_change_pct: float = 0.0
    funding_rate: float = 0.0

    # Order book (injected externally)
    ob_imbalance: float = 0.0   # [-1, 1]

    # Multi-exchange
    median_price: float = 0.0
    exchange_prices: dict = field(default_factory=dict)

    # Derived convenience
    @property
    def above_vwap(self) -> bool:
        return self.close > self.vwap

    @property
    def at_bb_lower(self) -> bool:
        return self.close <= self.bb_lower

    @property
    def at_bb_upper(self) -> bool:
        return self.close >= self.bb_upper

    @property
    def htf_aligned_up(self) -> bool:
        return self.htf_trend == 'up'

    @property
    def htf_aligned_down(self) -> bool:
        return self.htf_trend == 'down'

    @property
    def oi_rising(self) -> bool:
        return self.oi_change_pct > 0

    def to_ml_vector(self) -> list[float]:
        """Return a flat feature vector for XGBoost / ML models."""
        htf_enc = 1.0 if self.htf_trend == 'up' else (-1.0 if self.htf_trend == 'down' else 0.0)
        return [
            self.vwap_dist,
            self.ewma_diff,
            self.atr_pct,
            self.roc,
            self.rsi / 100.0,
            self.bb_pct,
            self.oi_change_pct,
            self.ob_imbalance,
            self.funding_rate * 1000,   # scale up small values
            htf_enc,
            self.htf_roc,
            self.btc_corr,
            float(self.hh),
            float(self.ll),
        ]

    @staticmethod
    def feature_names() -> list[str]:
        return [
            'vwap_dist', 'ewma_diff', 'atr_pct', 'roc', 'rsi_norm',
            'bb_pct', 'oi_change_pct', 'ob_imbalance', 'funding_rate_scaled',
            'htf_trend_enc', 'htf_roc', 'btc_corr', 'hh', 'll',
        ]


def _htf_trend(htf_df: pd.DataFrame) -> tuple[str, float]:
    """Determine higher timeframe trend from the last few bars."""
    if htf_df is None or len(htf_df) < 10:
        return 'neutral', 0.0
    # Use EWMA crossover on HTF
    df = indicators.add_ewma(htf_df)
    last = df.iloc[-1]
    roc = float((htf_df['close'].iloc[-1] - htf_df['close'].iloc[-5]) / htf_df['close'].iloc[-5])
    if last['ewma_short'] > last['ewma_long'] and roc > 0.005:
        return 'up', roc
    elif last['ewma_short'] < last['ewma_long'] and roc < -0.005:
        return 'down', roc
    return 'neutral', roc


def build_feature_set(symbol: str,
                      frames: dict[str, pd.DataFrame],
                      btc_frames: dict[str, pd.DataFrame] | None = None,
                      oi_current: float = 0.0,
                      oi_prev: float = 0.0,
                      funding_rate: float = 0.0,
                      ob_imbalance: float = 0.0,
                      median_price: float = 0.0,
                      exchange_prices: dict | None = None) -> FeatureSet:
    """
    Build a FeatureSet from multi-timeframe OHLCV DataFrames plus external
    market microstructure data.

    Parameters
    ----------
    symbol      : trading pair, e.g. 'BTCUSDT'
    frames      : dict of timeframe → OHLCV DataFrame (with indicators applied)
    btc_frames  : BTC OHLCV frames for correlation (None if asset is BTC)
    oi_current  : current open interest
    oi_prev     : previous open interest reading
    funding_rate: latest funding rate
    ob_imbalance: order book imbalance [-1, 1]
    median_price: median across exchanges
    exchange_prices: individual exchange prices
    """
    primary_tf = cfg.PRIMARY_TF
    htf = cfg.HTF

    primary_df = frames.get(primary_tf)
    if primary_df is None or primary_df.empty:
        return FeatureSet(symbol=symbol)

    # Apply all indicators to primary timeframe
    primary_df = indicators.compute_all(primary_df)

    # Add BTC correlation
    btc_primary = (btc_frames or {}).get(primary_tf)
    if btc_primary is not None and symbol != 'BTCUSDT':
        primary_df = correlation.add_btc_correlation(primary_df, btc_primary)
    else:
        primary_df['btc_corr'] = 1.0

    last = primary_df.iloc[-1]

    # Higher timeframe trend
    htf_df = frames.get(htf)
    trend_label, htf_roc = _htf_trend(htf_df)

    # OI change
    oi_change_pct = 0.0
    if oi_prev and oi_prev > 0:
        oi_change_pct = (oi_current - oi_prev) / oi_prev

    fs = FeatureSet(
        symbol=symbol,
        close=float(last['close']),
        open_=float(last['open']),
        high=float(last['high']),
        low=float(last['low']),
        volume=float(last['volume']),
        vwap=float(last.get('vwap', last['close'])),
        vwap_dist=float(last.get('vwap_dist', 0.0)),
        ewma_short=float(last.get('ewma_short', last['close'])),
        ewma_long=float(last.get('ewma_long', last['close'])),
        ewma_diff=float(last.get('ewma_diff', 0.0)),
        atr=float(last.get('atr', 0.0)),
        atr_pct=float(last.get('atr_pct', 0.0)),
        bb_upper=float(last.get('bb_upper', last['close'])),
        bb_lower=float(last.get('bb_lower', last['close'])),
        bb_mid=float(last.get('bb_mid', last['close'])),
        bb_pct=float(last.get('bb_pct', 0.5)),
        roc=float(last.get('roc', 0.0)),
        rsi=float(last.get('rsi', 50.0)),
        hh=bool(last.get('hh', False)),
        ll=bool(last.get('ll', False)),
        trend_score=int(last.get('trend_score', 0)),
        htf_trend=trend_label,
        htf_roc=htf_roc,
        btc_corr=float(last.get('btc_corr', 0.5)),
        oi_current=oi_current,
        oi_prev=oi_prev,
        oi_change_pct=oi_change_pct,
        funding_rate=funding_rate,
        ob_imbalance=ob_imbalance,
        median_price=median_price or float(last['close']),
        exchange_prices=exchange_prices or {},
    )
    return fs
