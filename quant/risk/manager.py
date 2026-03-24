"""
risk/manager.py — Position sizing, stop/target calculation, and time-decay exit.

ATR-based stops and targets:
  Stop loss   = entry ± ATR_STOP_MULT × ATR
  Take profit = entry ± ATR_TP_MULT × ATR

Fractional Kelly sizing:
  kelly_full = (win_rate × avg_win − (1-win_rate) × avg_loss) / avg_win
  kelly_frac = KELLY_FRACTION × kelly_full   (default 0.25)
  Capped at 0.5 Kelly and 1% of capital per trade.

Time-decay exit:
  Exit early if no meaningful PnL movement after MAX_HOLD_MINUTES.
"""

from __future__ import annotations

from dataclasses import dataclass

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg


@dataclass
class RiskLevels:
    entry: float
    stop_loss: float
    take_profit: float
    atr: float
    risk_pct: float          # (entry − stop) / entry
    reward_pct: float        # (tp − entry) / entry
    rr_ratio: float          # reward / risk
    kelly_fraction: float
    max_position_pct: float  # max % of capital to deploy


# ─── Stop / Target calculation ────────────────────────────────────────────────

def compute_levels(entry: float,
                   atr: float,
                   direction: str,
                   stop_mult: float = cfg.ATR_STOP_MULT,
                   tp_mult: float = cfg.ATR_TP_MULT,
                   win_rate: float = 0.50) -> RiskLevels:
    """
    Compute stop loss, take profit, and Kelly position size.

    Parameters
    ----------
    entry     : trade entry price
    atr       : current ATR value
    direction : 'BUY' or 'SELL'
    stop_mult : ATR multiplier for stop (default 1.75)
    tp_mult   : ATR multiplier for take profit (default 2.5)
    win_rate  : historical win rate (used for Kelly); defaults to 50%

    Returns
    -------
    RiskLevels dataclass
    """
    if direction == 'BUY':
        stop_loss   = entry - stop_mult * atr
        take_profit = entry + tp_mult   * atr
    elif direction == 'SELL':
        stop_loss   = entry + stop_mult * atr
        take_profit = entry - tp_mult   * atr
    else:
        return RiskLevels(entry, entry, entry, atr, 0, 0, 0, 0, 0)

    risk_amt   = abs(entry - stop_loss)
    reward_amt = abs(take_profit - entry)
    risk_pct   = risk_amt   / entry
    reward_pct = reward_amt / entry
    rr_ratio   = reward_amt / risk_amt if risk_amt > 0 else 0

    kelly = _fractional_kelly(
        win_rate=win_rate,
        avg_win=tp_mult * atr,
        avg_loss=stop_mult * atr,
    )

    # Cap position size at MAX_RISK_PER_TRADE / risk_pct
    # e.g. 1% risk budget, 1.27% stop → max 0.79 of capital
    max_pos = cfg.MAX_RISK_PER_TRADE / risk_pct if risk_pct > 0 else 0

    return RiskLevels(
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        atr=atr,
        risk_pct=risk_pct,
        reward_pct=reward_pct,
        rr_ratio=rr_ratio,
        kelly_fraction=kelly,
        max_position_pct=min(kelly, max_pos),
    )


def _fractional_kelly(win_rate: float,
                      avg_win: float,
                      avg_loss: float) -> float:
    """
    Compute fractional Kelly (KELLY_FRACTION × full Kelly).

    Full Kelly f* = (p×b − q) / b
    where p=win_rate, q=1-p, b=avg_win/avg_loss (odds ratio).

    Clamped to [0, 0.5] Kelly fraction.
    """
    if avg_loss <= 0:
        return 0.0
    b = avg_win / avg_loss
    q = 1 - win_rate
    kelly_full = (win_rate * b - q) / b
    kelly_full = max(0.0, kelly_full)
    return min(cfg.KELLY_FRACTION * kelly_full, 0.5)


# ─── Time-decay exit ──────────────────────────────────────────────────────────

@dataclass
class ExitSignal:
    should_exit: bool = False
    reason: str = ''


def check_time_decay_exit(entry_time_unix: float,
                          entry_price: float,
                          current_price: float,
                          current_fs,
                          direction: str) -> ExitSignal:
    """
    Determine if an open trade should be exited early based on:
    1. Age > MAX_HOLD_MINUTES with negligible PnL
    2. Opposing signal conditions appearing

    Parameters
    ----------
    entry_time_unix : Unix timestamp of trade entry
    entry_price     : price at entry
    current_price   : current market price
    current_fs      : current FeatureSet
    direction       : 'BUY' or 'SELL'

    Returns
    -------
    ExitSignal with should_exit flag and reason string
    """
    import time

    age_minutes = (time.time() - entry_time_unix) / 60
    pnl_pct = (current_price - entry_price) / entry_price
    if direction == 'SELL':
        pnl_pct = -pnl_pct

    # 1. Time-decay: no movement after hold period
    if age_minutes > cfg.MAX_HOLD_MINUTES and abs(pnl_pct) < cfg.DECAY_PNL_THRESHOLD:
        return ExitSignal(True, f"time_decay: {age_minutes:.0f} min held, PnL={pnl_pct:+.3%}")

    # 2. Momentum reversal
    if direction == 'BUY' and current_fs.roc < -cfg.TREND_ROC_MIN * 2:
        return ExitSignal(True, f"momentum_reversal: ROC={current_fs.roc:+.3%}")
    if direction == 'SELL' and current_fs.roc > cfg.TREND_ROC_MIN * 2:
        return ExitSignal(True, f"momentum_reversal: ROC={current_fs.roc:+.3%}")

    # 3. OBI flips strongly against position
    if direction == 'BUY' and current_fs.ob_imbalance < -0.3:
        return ExitSignal(True, f"ob_reversal: OBI={current_fs.ob_imbalance:+.2f}")
    if direction == 'SELL' and current_fs.ob_imbalance > 0.3:
        return ExitSignal(True, f"ob_reversal: OBI={current_fs.ob_imbalance:+.2f}")

    return ExitSignal(False, '')
