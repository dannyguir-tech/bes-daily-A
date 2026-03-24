"""
signals/mean_reversion.py — Mean-reversion signal generator.

BUY  when: price at lower Bollinger Band, below VWAP,
           weak momentum, funding rate deeply negative (contrarian).
SELL when: price at upper Bollinger Band, above VWAP,
           weak momentum, funding rate deeply positive.
NEUTRAL when conditions are not all met.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg
from signals.trend import Signal, Direction


def generate(fs) -> Signal:
    """
    Evaluate all mean-reversion BUY/SELL conditions.

    Mean reversion trades require ALL 4 conditions in the same direction.
    The signal requires price to have actually touched the band (not just
    be near it) for stronger edge.

    Parameters
    ----------
    fs : features.multi_timeframe.FeatureSet
    """
    buy_conditions: list[tuple[bool, str]] = [
        (fs.at_bb_lower,                                   f'Price at BB lower ({fs.bb_lower:.2f})'),
        (not fs.above_vwap,                                f'Price below VWAP ({fs.vwap:.2f})'),
        (abs(fs.roc) < cfg.MR_ROC_MAX,                    f'Momentum weak ROC={fs.roc:+.3%}'),
        (fs.funding_rate < cfg.MR_FUNDING_THRESHOLD,       f'Funding rate negative {fs.funding_rate:.4%}'),
    ]

    sell_conditions: list[tuple[bool, str]] = [
        (fs.at_bb_upper,                                   f'Price at BB upper ({fs.bb_upper:.2f})'),
        (fs.above_vwap,                                    f'Price above VWAP ({fs.vwap:.2f})'),
        (abs(fs.roc) < cfg.MR_ROC_MAX,                    f'Momentum weak ROC={fs.roc:+.3%}'),
        (fs.funding_rate > -cfg.MR_FUNDING_THRESHOLD,      f'Funding rate positive {fs.funding_rate:.4%}'),
    ]

    buy_met   = [label for cond, label in buy_conditions  if cond]
    buy_fail  = [label for cond, label in buy_conditions  if not cond]
    sell_met  = [label for cond, label in sell_conditions if cond]
    sell_fail = [label for cond, label in sell_conditions if not cond]

    n = len(buy_conditions)

    if len(buy_met) == n:
        return Signal('BUY',  'mean_reversion', buy_met,  buy_fail,  strength=1.0)
    if len(sell_met) == n:
        return Signal('SELL', 'mean_reversion', sell_met, sell_fail, strength=1.0)

    if len(buy_met) >= len(sell_met):
        return Signal('NEUTRAL', 'mean_reversion', buy_met,  buy_fail,  strength=len(buy_met)  / n)
    return Signal('NEUTRAL', 'mean_reversion', sell_met, sell_fail, strength=len(sell_met) / n)
