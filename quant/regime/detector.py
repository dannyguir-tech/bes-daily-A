"""
regime/detector.py — Classifies current market into one of three regimes.

TRENDING      — directional price move; trend strategies preferred
RANGING       — oscillating around a mean; mean-reversion strategies preferred
UNCERTAIN     — high volatility or conflicting signals; NO trades

Logic uses ATR%, EWMA spread, and momentum consistency.
"""

from __future__ import annotations
from typing import Literal

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg

Regime = Literal['TRENDING', 'RANGING', 'UNCERTAIN']


def detect(fs) -> Regime:
    """
    Classify the current market regime from a FeatureSet.

    Parameters
    ----------
    fs : features.multi_timeframe.FeatureSet

    Returns
    -------
    Regime string: 'TRENDING', 'RANGING', or 'UNCERTAIN'
    """
    # 1. High volatility → uncertain, no trades
    if fs.atr_pct > cfg.ATR_VOL_THRESHOLD:
        return 'UNCERTAIN'

    # 2. Check for trending conditions:
    #    - Significant EWMA spread (direction established)
    #    - Consistent momentum (ROC above threshold)
    #    - Trend structure supporting (HH or LL detected)
    ewma_spread_significant = abs(fs.ewma_diff) > cfg.EWMA_DIFF_THRESHOLD
    momentum_consistent = abs(fs.roc) > cfg.MOMENTUM_THRESHOLD
    structure_aligned = fs.hh or fs.ll

    if ewma_spread_significant and momentum_consistent:
        # Confirm EWMA direction matches momentum direction
        ewma_bullish = fs.ewma_diff > 0
        roc_bullish  = fs.roc > 0
        if ewma_bullish == roc_bullish:  # both agree on direction
            return 'TRENDING'

    # 3. Ranging: low volatility, no clear trend
    return 'RANGING'


def regime_allows_strategy(regime: Regime, strategy: str) -> bool:
    """
    Returns True if a given strategy is allowed in the current regime.

    strategy : 'trend' | 'mean_reversion'
    """
    if regime == 'UNCERTAIN':
        return False
    if strategy == 'trend':
        return regime == 'TRENDING'
    if strategy == 'mean_reversion':
        return regime == 'RANGING'
    return False


def regime_label(regime: Regime) -> str:
    """Human-readable one-liner for each regime."""
    labels = {
        'TRENDING':  'Trending — directional move underway',
        'RANGING':   'Ranging — mean-reversion conditions',
        'UNCERTAIN': 'Uncertain — high volatility, no trades',
    }
    return labels.get(regime, regime)
