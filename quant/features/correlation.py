"""
features/correlation.py — Rolling BTC correlation for each asset.

A high positive correlation with BTC means the asset tends to move with the
market. A divergence (asset moving independently) can be a signal.
"""

import numpy as np
import pandas as pd

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg


def compute_btc_correlation(asset_df: pd.DataFrame,
                            btc_df: pd.DataFrame,
                            period: int = cfg.CORR_PERIOD) -> pd.Series:
    """
    Compute rolling Pearson correlation between asset returns and BTC returns.

    Parameters
    ----------
    asset_df : OHLCV DataFrame for the asset
    btc_df   : OHLCV DataFrame for BTC (same interval)
    period   : rolling window length

    Returns
    -------
    pd.Series named 'btc_corr', aligned to asset_df index, values in [-1, 1].
    NaN for the first `period` rows.
    """
    asset_ret = asset_df['close'].pct_change()
    btc_ret   = btc_df['close'].pct_change()

    # Align on the asset index (BTC may have slightly different timestamps)
    btc_ret = btc_ret.reindex(asset_df.index).ffill()

    corr = asset_ret.rolling(period, min_periods=period // 2).corr(btc_ret)
    corr.name = 'btc_corr'
    return corr


def add_btc_correlation(asset_df: pd.DataFrame,
                        btc_df: pd.DataFrame,
                        period: int = cfg.CORR_PERIOD) -> pd.DataFrame:
    """
    Add 'btc_corr' column to asset_df in-place (returns copy).
    If asset IS BTC, btc_corr is set to 1.0.
    """
    df = asset_df.copy()
    if btc_df is None or btc_df.empty or asset_df is btc_df:
        df['btc_corr'] = 1.0
    else:
        df['btc_corr'] = compute_btc_correlation(asset_df, btc_df, period)
    return df


def correlation_score(corr_value: float) -> float:
    """
    Normalize correlation [-1,1] to a [0,1] 'corr_score' for use in feature
    vectors. Mid (0.0 correlation) maps to 0.5.
    """
    if np.isnan(corr_value):
        return 0.5
    return (corr_value + 1) / 2
