"""
data/normalizer.py — Aligns multi-exchange OHLCV data, computes median prices,
fills gaps, and removes outliers.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass, field

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg


@dataclass
class MultiTimeframeData:
    """Container for all timeframe DataFrames for a single symbol."""
    symbol: str
    # Key: timeframe string ('1m', '5m', '15m', '1h') → OHLCV DataFrame
    frames: dict = field(default_factory=dict)
    # Median close price across exchanges (latest)
    median_price: float = 0.0
    # Exchange prices at latest tick
    exchange_prices: dict = field(default_factory=dict)


def compute_median_price(exchange_dfs: dict[str, pd.DataFrame]) -> tuple[float, dict]:
    """
    Given OHLCV DataFrames from multiple exchanges, return the median of their
    most recent close prices and a dict of individual exchange prices.
    """
    prices = {}
    for exchange, df in exchange_dfs.items():
        if df is not None and not df.empty:
            prices[exchange] = float(df['close'].iloc[-1])
    if not prices:
        return 0.0, {}
    return float(np.median(list(prices.values()))), prices


def remove_outliers(df: pd.DataFrame, sigma: float = 5.0) -> pd.DataFrame:
    """
    Drop candles where the close price deviates more than sigma standard
    deviations from the rolling mean (window=20). Replaces with NaN then
    forward-fills to preserve index continuity.
    """
    if len(df) < 20:
        return df
    close = df['close']
    roll_mean = close.rolling(20, min_periods=5).mean()
    roll_std  = close.rolling(20, min_periods=5).std()
    outlier_mask = (close - roll_mean).abs() > sigma * roll_std
    df = df.copy()
    df.loc[outlier_mask] = np.nan
    df = df.ffill()
    return df


def fill_gaps(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    """
    Reindex a OHLCV DataFrame to a regular time grid, forward-filling any
    missing candles (e.g. from exchange downtime).
    """
    if df is None or df.empty:
        return df
    freq_map = {'1m': '1min', '5m': '5min', '15m': '15min', '1h': '1h'}
    freq = freq_map.get(interval, '5min')
    full_index = pd.date_range(start=df.index[0], end=df.index[-1], freq=freq, tz='UTC')
    df = df.reindex(full_index).ffill()
    return df


def align_to_primary(frames: dict[str, pd.DataFrame], primary: str = cfg.PRIMARY_TF) -> dict[str, pd.DataFrame]:
    """
    Trim all timeframes so they end at the same UTC timestamp as the primary
    timeframe. This ensures HTF and LTF data are in sync.
    """
    if primary not in frames or frames[primary] is None:
        return frames
    primary_end = frames[primary].index[-1]
    aligned = {}
    for tf, df in frames.items():
        if df is None or df.empty:
            aligned[tf] = df
            continue
        aligned[tf] = df[df.index <= primary_end]
    return aligned


def normalize_all(exchange_dfs: dict[str, pd.DataFrame], interval: str) -> pd.DataFrame | None:
    """
    Given raw OHLCV DataFrames from multiple exchanges for the same interval,
    return a single consensus DataFrame using the median close price.

    For open/high/low/volume we use the Binance data as the primary source
    (most liquid), but substitute the median close.
    """
    if not exchange_dfs:
        return None

    # Use Binance as the structural template
    base = exchange_dfs.get('binance') or next(iter(exchange_dfs.values()))
    base = fill_gaps(base, interval)
    base = remove_outliers(base)

    # Build a median close series across available exchanges
    close_series = []
    for df in exchange_dfs.values():
        df = fill_gaps(df, interval)
        df = remove_outliers(df)
        # Reindex to base index
        df = df.reindex(base.index).ffill()
        close_series.append(df['close'])

    if close_series:
        median_close = pd.concat(close_series, axis=1).median(axis=1)
        base = base.copy()
        base['close'] = median_close

    return base
