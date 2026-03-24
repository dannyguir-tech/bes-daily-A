"""
signals/scorer.py — Scores a signal on 6 dimensions (0–100 total).

Scoring breakdown:
  Trend alignment      (0–20): HTF trend matches signal direction
  VWAP alignment       (0–15): price distance from VWAP in signal direction
  Order book           (0–15): OBI magnitude confirms signal
  OI confirmation      (0–15): OI change direction matches signal
  Momentum quality     (0–15): ROC strength and RSI position
  Risk/reward ratio    (0–20): (TP − entry) / (entry − SL) ≥ MIN_R_R

Only signals scoring ≥ SCORE_THRESHOLD (default 70) proceed to ML filter.
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg
from signals.trend import Signal


def score(fs, signal: Signal, stop_loss: float, take_profit: float) -> int:
    """
    Score a signal from 0 to 100.

    Parameters
    ----------
    fs          : FeatureSet
    signal      : Signal (must have direction BUY or SELL)
    stop_loss   : computed stop loss price
    take_profit : computed take profit price

    Returns
    -------
    int in [0, 100]
    """
    direction = signal.direction
    if direction not in ('BUY', 'SELL'):
        return 0

    is_long = direction == 'BUY'
    total = 0

    # ── 1. Trend alignment (0–20) ──────────────────────────────────────────
    w = cfg.SCORE_WEIGHTS['trend_alignment']
    if is_long:
        if fs.htf_aligned_up:
            total += w           # full score: HTF confirms
        elif fs.htf_trend == 'neutral':
            total += w // 2      # half score: neutral HTF
        # else: HTF opposes → 0
    else:
        if fs.htf_aligned_down:
            total += w
        elif fs.htf_trend == 'neutral':
            total += w // 2

    # ── 2. VWAP alignment (0–15) ───────────────────────────────────────────
    w = cfg.SCORE_WEIGHTS['vwap_alignment']
    vwap_dist_abs = abs(fs.vwap_dist)
    if is_long and fs.above_vwap:
        # Closer to VWAP but above = better entry; far above = chasing
        vwap_score = w * max(0.0, 1.0 - vwap_dist_abs / 0.05)
        total += round(vwap_score)
    elif not is_long and not fs.above_vwap:
        vwap_score = w * max(0.0, 1.0 - vwap_dist_abs / 0.05)
        total += round(vwap_score)
    elif is_long and not fs.above_vwap and fs.at_bb_lower:
        # Mean reversion BUY below VWAP at BB lower — partial VWAP credit
        total += w // 3

    # ── 3. Order book confirmation (0–15) ──────────────────────────────────
    w = cfg.SCORE_WEIGHTS['order_book']
    obi = fs.ob_imbalance
    if is_long and obi > 0:
        total += round(w * min(obi, 1.0))
    elif not is_long and obi < 0:
        total += round(w * min(abs(obi), 1.0))

    # ── 4. OI confirmation (0–15) ──────────────────────────────────────────
    w = cfg.SCORE_WEIGHTS['oi_confirmation']
    if is_long and fs.oi_rising:
        oi_score = w * min(abs(fs.oi_change_pct) / 0.02, 1.0)  # cap at 2% OI change
        total += round(oi_score)
    elif not is_long and not fs.oi_rising:
        oi_score = w * min(abs(fs.oi_change_pct) / 0.02, 1.0)
        total += round(oi_score)

    # ── 5. Momentum quality (0–15) ────────────────────────────────────────
    w = cfg.SCORE_WEIGHTS['momentum_quality']
    roc_abs = abs(fs.roc)
    rsi = fs.rsi
    if is_long:
        # Strong positive ROC, RSI between 50 and 70 (not overbought)
        roc_score  = min(roc_abs / 0.03, 1.0)          # max at 3% ROC
        rsi_score  = 1.0 if 50 < rsi < 70 else (0.5 if 40 < rsi <= 80 else 0.0)
        total += round(w * 0.6 * roc_score + w * 0.4 * rsi_score)
    else:
        roc_score = min(roc_abs / 0.03, 1.0)
        rsi_score = 1.0 if 30 < rsi < 50 else (0.5 if 20 < rsi <= 60 else 0.0)
        total += round(w * 0.6 * roc_score + w * 0.4 * rsi_score)

    # ── 6. Risk/reward ratio (0–20) ────────────────────────────────────────
    w = cfg.SCORE_WEIGHTS['risk_reward']
    entry = fs.close
    risk   = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    if risk > 0:
        rr = reward / risk
        if rr >= cfg.MIN_RISK_REWARD * 1.5:    # e.g. R:R >= 3.0 → full score
            total += w
        elif rr >= cfg.MIN_RISK_REWARD:         # R:R >= 2.0 → partial
            total += round(w * (rr - cfg.MIN_RISK_REWARD) / cfg.MIN_RISK_REWARD + w * 0.5)
        # else R:R < 2.0 → 0

    return min(int(total), 100)


def score_breakdown(fs, signal: Signal, stop_loss: float, take_profit: float) -> dict:
    """Return individual dimension scores for transparency in alerts."""
    direction = signal.direction
    is_long = direction == 'BUY'
    entry = fs.close

    breakdown = {}

    # Trend (max 20)
    w = cfg.SCORE_WEIGHTS['trend_alignment']
    if is_long:
        breakdown['trend_alignment'] = w if fs.htf_aligned_up else (w // 2 if fs.htf_trend == 'neutral' else 0)
    else:
        breakdown['trend_alignment'] = w if fs.htf_aligned_down else (w // 2 if fs.htf_trend == 'neutral' else 0)

    # VWAP (max 15)
    w = cfg.SCORE_WEIGHTS['vwap_alignment']
    vd = abs(fs.vwap_dist)
    if (is_long and fs.above_vwap) or (not is_long and not fs.above_vwap):
        breakdown['vwap_alignment'] = round(w * max(0.0, 1.0 - vd / 0.05))
    else:
        breakdown['vwap_alignment'] = w // 3 if (is_long and fs.at_bb_lower) else 0

    # OB (max 15)
    w = cfg.SCORE_WEIGHTS['order_book']
    obi = fs.ob_imbalance
    if is_long and obi > 0:
        breakdown['order_book'] = round(w * min(obi, 1.0))
    elif not is_long and obi < 0:
        breakdown['order_book'] = round(w * min(abs(obi), 1.0))
    else:
        breakdown['order_book'] = 0

    # OI (max 15)
    w = cfg.SCORE_WEIGHTS['oi_confirmation']
    oi_match = (is_long and fs.oi_rising) or (not is_long and not fs.oi_rising)
    breakdown['oi_confirmation'] = round(w * min(abs(fs.oi_change_pct) / 0.02, 1.0)) if oi_match else 0

    # Momentum (max 15)
    w = cfg.SCORE_WEIGHTS['momentum_quality']
    roc_score = min(abs(fs.roc) / 0.03, 1.0)
    rsi = fs.rsi
    if is_long:
        rsi_score = 1.0 if 50 < rsi < 70 else (0.5 if 40 < rsi <= 80 else 0.0)
    else:
        rsi_score = 1.0 if 30 < rsi < 50 else (0.5 if 20 < rsi <= 60 else 0.0)
    breakdown['momentum_quality'] = round(w * 0.6 * roc_score + w * 0.4 * rsi_score)

    # R:R (max 20)
    w = cfg.SCORE_WEIGHTS['risk_reward']
    risk = abs(entry - stop_loss)
    reward = abs(take_profit - entry)
    rr = reward / risk if risk > 0 else 0
    if rr >= cfg.MIN_RISK_REWARD * 1.5:
        breakdown['risk_reward'] = w
    elif rr >= cfg.MIN_RISK_REWARD:
        breakdown['risk_reward'] = round(w * (rr - cfg.MIN_RISK_REWARD) / cfg.MIN_RISK_REWARD + w * 0.5)
    else:
        breakdown['risk_reward'] = 0

    breakdown['total'] = sum(breakdown.values())
    breakdown['rr_ratio'] = round(rr, 2)
    return breakdown
