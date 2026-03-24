"""
models/ensemble.py — Ensemble decision engine.

Combines:
  1. Strategy signal strength  (trend or mean-reversion)
  2. Trade score               (0–100 rule-based)
  3. ML probability            (XGBoost P(success))

into a final BUY / SELL / NO TRADE decision with a confidence score.

All three gates must pass independently:
  - signal.direction must be BUY or SELL
  - score >= SCORE_THRESHOLD (default 70)
  - ml_prob >= ML_PROB_THRESHOLD (default 0.6)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg
from signals.trend import Signal


@dataclass
class Decision:
    action: str = 'NO TRADE'        # 'BUY', 'SELL', 'NO TRADE'
    confidence: float = 0.0         # 0–100
    entry: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    kelly_fraction: float = 0.0
    regime: str = 'UNKNOWN'
    strategy: str = ''
    signal_strength: float = 0.0
    score: int = 0
    score_breakdown: dict = field(default_factory=dict)
    ml_prob: float = 0.0
    conditions_met: list[str] = field(default_factory=list)
    reject_reason: str = ''         # populated when action == 'NO TRADE'

    @property
    def is_trade(self) -> bool:
        return self.action in ('BUY', 'SELL')

    def summary_line(self) -> str:
        if not self.is_trade:
            return f"NO TRADE — {self.reject_reason}"
        sl_pct = (self.stop_loss - self.entry) / self.entry * 100
        tp_pct = (self.take_profit - self.entry) / self.entry * 100
        return (
            f"{self.action} | Confidence {self.confidence:.0f}/100 | "
            f"Entry {self.entry:.4f} | SL {self.stop_loss:.4f} ({sl_pct:+.2f}%) | "
            f"TP {self.take_profit:.4f} ({tp_pct:+.2f}%) | Kelly {self.kelly_fraction:.3f}"
        )


def decide(signal: Signal,
           score: int,
           score_bd: dict,
           ml_prob: float,
           fs,
           stop_loss: float,
           take_profit: float,
           kelly_fraction: float,
           regime: str) -> Decision:
    """
    Run all three gates and produce a final Decision.

    Parameters
    ----------
    signal       : Signal from trend or mean_reversion
    score        : int 0–100
    score_bd     : score breakdown dict
    ml_prob      : float 0–1 from XGBoost
    fs           : FeatureSet
    stop_loss    : float
    take_profit  : float
    kelly_fraction : float
    regime       : str
    """
    base = Decision(
        entry=fs.close,
        stop_loss=stop_loss,
        take_profit=take_profit,
        kelly_fraction=kelly_fraction,
        regime=regime,
        strategy=signal.strategy,
        signal_strength=signal.strength,
        score=score,
        score_breakdown=score_bd,
        ml_prob=ml_prob,
        conditions_met=signal.conditions_met,
    )

    # ── Gate 1: signal must be directional ───────────────────────────────────
    if not signal.is_actionable:
        base.reject_reason = f"Signal NEUTRAL (strength={signal.strength:.2f})"
        return base

    # ── Gate 2: regime gate ───────────────────────────────────────────────────
    if regime == 'UNCERTAIN':
        base.reject_reason = "Regime UNCERTAIN — no trades allowed"
        return base

    # ── Gate 3: score gate ────────────────────────────────────────────────────
    if score < cfg.SCORE_THRESHOLD:
        base.reject_reason = f"Score {score} < threshold {cfg.SCORE_THRESHOLD}"
        return base

    # ── Gate 4: ML probability gate ───────────────────────────────────────────
    if ml_prob < cfg.ML_PROB_THRESHOLD:
        base.reject_reason = f"ML prob {ml_prob:.2f} < threshold {cfg.ML_PROB_THRESHOLD}"
        return base

    # ── All gates passed — compute confidence ─────────────────────────────────
    w = cfg.ENSEMBLE_WEIGHTS
    confidence = (
        w['signal_strength'] * signal.strength +
        w['score']           * (score / 100) +
        w['ml_prob']         * ml_prob
    ) * 100

    base.action     = signal.direction
    base.confidence = round(confidence, 1)
    return base
