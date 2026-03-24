"""
signals/trend.py — Trend-following signal generator.

BUY  when: price > VWAP, momentum breakout, HTF aligned up,
           OI rising with price, order book imbalance positive.
SELL when: inverse of the above conditions.
NEUTRAL when fewer than required conditions are met.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg

Direction = Literal['BUY', 'SELL', 'NEUTRAL']


@dataclass
class Signal:
    direction: Direction = 'NEUTRAL'
    strategy: str = 'trend'
    conditions_met: list[str] = field(default_factory=list)
    conditions_failed: list[str] = field(default_factory=list)
    strength: float = 0.0   # 0–1; fraction of conditions met

    @property
    def is_actionable(self) -> bool:
        return self.direction in ('BUY', 'SELL')


def generate(fs) -> Signal:
    """
    Evaluate all trend BUY/SELL conditions against the FeatureSet.

    Requires ALL 5 conditions to fire in the same direction.
    If 3+ conditions are met but not all 5, signal is NEUTRAL.

    Parameters
    ----------
    fs : features.multi_timeframe.FeatureSet
    """
    buy_conditions: list[tuple[bool, str]] = [
        (fs.above_vwap,                           'Price > VWAP'),
        (fs.roc > cfg.TREND_ROC_MIN,              f'Momentum breakout ROC={fs.roc:+.3%}'),
        (fs.htf_aligned_up,                       f'HTF ({cfg.HTF}) trend UP'),
        (fs.oi_rising,                            f'OI rising {fs.oi_change_pct:+.2%}'),
        (fs.ob_imbalance > cfg.TREND_OBI_MIN,     f'Order book bid pressure OBI={fs.ob_imbalance:+.2f}'),
    ]

    sell_conditions: list[tuple[bool, str]] = [
        (not fs.above_vwap,                       'Price < VWAP'),
        (fs.roc < -cfg.TREND_ROC_MIN,             f'Momentum breakdown ROC={fs.roc:+.3%}'),
        (fs.htf_aligned_down,                     f'HTF ({cfg.HTF}) trend DOWN'),
        (not fs.oi_rising,                        f'OI falling {fs.oi_change_pct:+.2%}'),
        (fs.ob_imbalance < -cfg.TREND_OBI_MIN,    f'Order book ask pressure OBI={fs.ob_imbalance:+.2f}'),
    ]

    buy_met   = [label for cond, label in buy_conditions  if cond]
    buy_fail  = [label for cond, label in buy_conditions  if not cond]
    sell_met  = [label for cond, label in sell_conditions if cond]
    sell_fail = [label for cond, label in sell_conditions if not cond]

    n = len(buy_conditions)

    if len(buy_met) == n:
        return Signal('BUY',  'trend', buy_met,  buy_fail,  strength=1.0)
    if len(sell_met) == n:
        return Signal('SELL', 'trend', sell_met, sell_fail, strength=1.0)

    # Partial signals — strength < 1.0, direction = NEUTRAL
    if len(buy_met) >= len(sell_met):
        return Signal('NEUTRAL', 'trend', buy_met, buy_fail, strength=len(buy_met) / n)
    return Signal('NEUTRAL', 'trend', sell_met, sell_fail, strength=len(sell_met) / n)
