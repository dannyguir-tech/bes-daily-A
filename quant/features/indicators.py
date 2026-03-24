"""
features/indicators.py — Pure NumPy/Pandas technical indicator computations.

All functions accept a pd.DataFrame with columns [open, high, low, close, volume]
and return a new DataFrame with the original columns plus computed indicator columns.
"""

import numpy as np
import pandas as pd
from datetime import timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg


def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Session VWAP (resets at 00:00 UTC each day).
    VWAP = cumulative(typical_price × volume) / cumulative(volume) within session.
    """
    df = df.copy()
    typical = (df['high'] + df['low'] + df['close']) / 3
    pv = typical * df['volume']

    # Group by UTC date for daily reset
    dates = df.index.normalize()
    df['vwap'] = (
        pv.groupby(dates).cumsum() /
        df['volume'].groupby(dates).cumsum()
    )
    return df


def add_ewma(df: pd.DataFrame,
             short: int = cfg.EWMA_SHORT,
             long_: int = cfg.EWMA_LONG) -> pd.DataFrame:
    """Add short and long EWMA of close price, plus their difference."""
    df = df.copy()
    df['ewma_short'] = df['close'].ewm(span=short, adjust=False).mean()
    df['ewma_long']  = df['close'].ewm(span=long_,  adjust=False).mean()
    df['ewma_diff']  = (df['ewma_short'] - df['ewma_long']) / df['close']
    return df


def add_atr(df: pd.DataFrame, period: int = cfg.ATR_PERIOD) -> pd.DataFrame:
    """
    Average True Range (Wilder smoothing).
    ATR reflects recent volatility; used for stop/target sizing.
    """
    df = df.copy()
    prev_close = df['close'].shift(1)
    tr = pd.concat([
        df['high'] - df['low'],
        (df['high'] - prev_close).abs(),
        (df['low']  - prev_close).abs(),
    ], axis=1).max(axis=1)
    # Wilder smoothing = exponential with alpha = 1/period
    df['atr'] = tr.ewm(alpha=1.0 / period, adjust=False).mean()
    df['atr_pct'] = df['atr'] / df['close']   # normalized ATR
    return df


def add_bollinger_bands(df: pd.DataFrame,
                        period: int = cfg.BB_PERIOD,
                        std_mult: float = cfg.BB_STD) -> pd.DataFrame:
    """
    Bollinger Bands: SMA ± N×std over a rolling window.
    Also adds %B: position of price within the bands (0=lower, 1=upper).
    """
    df = df.copy()
    sma = df['close'].rolling(period, min_periods=period // 2).mean()
    std = df['close'].rolling(period, min_periods=period // 2).std()
    df['bb_mid']   = sma
    df['bb_upper'] = sma + std_mult * std
    df['bb_lower'] = sma - std_mult * std
    band_width = df['bb_upper'] - df['bb_lower']
    df['bb_pct'] = (df['close'] - df['bb_lower']) / band_width.replace(0, np.nan)
    return df


def add_momentum(df: pd.DataFrame, period: int = cfg.ROC_PERIOD) -> pd.DataFrame:
    """
    Rate of Change (ROC) as a decimal fraction.
    ROC > 0 → price rising; ROC < 0 → price falling.
    Also adds RSI-14.
    """
    df = df.copy()
    # ROC
    df['roc'] = (df['close'] - df['close'].shift(period)) / df['close'].shift(period)

    # RSI-14 using Wilder smoothing
    delta = df['close'].diff()
    gain  = delta.clip(lower=0)
    loss  = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1/14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    df['rsi'] = 100 - (100 / (1 + rs))

    return df


def add_trend_structure(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """
    Detect higher-highs / lower-lows over a rolling lookback window.
    hh = current high > max of previous `lookback` highs
    ll = current low  < min of previous `lookback` lows
    trend_score: +1 = HH (bullish), -1 = LL (bearish), 0 = neither
    """
    df = df.copy()
    prev_high_max = df['high'].shift(1).rolling(lookback).max()
    prev_low_min  = df['low'].shift(1).rolling(lookback).min()
    df['hh'] = df['high'] > prev_high_max
    df['ll'] = df['low']  < prev_low_min
    df['trend_score'] = np.where(df['hh'], 1, np.where(df['ll'], -1, 0))
    return df


def add_vwap_distance(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add vwap_dist: signed % distance of close from VWAP.
    Positive = above VWAP (bullish bias), negative = below (bearish bias).
    """
    df = df.copy()
    if 'vwap' not in df.columns:
        df = add_vwap(df)
    df['vwap_dist'] = (df['close'] - df['vwap']) / df['vwap']
    return df


def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    """Apply all indicators to a raw OHLCV DataFrame in one call."""
    df = add_vwap(df)
    df = add_ewma(df)
    df = add_atr(df)
    df = add_bollinger_bands(df)
    df = add_momentum(df)
    df = add_trend_structure(df)
    df = add_vwap_distance(df)
    return df
