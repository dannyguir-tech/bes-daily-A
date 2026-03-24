"""
alerts/emitter.py — Structured signal output for the quant engine.

Writes formatted alerts to:
  - stdout (always)
  - alerts.log (shared with Node.js system, if QUANT_LOG_FILE is set)
  - quant/signals/latest.json (machine-readable, for Node.js to optionally read)

Output format:
  ============================================================
    QUANT SIGNAL: BTCUSDT  [BUY]
    2026-03-24T19:45:00Z
  ============================================================
  Confidence:   82/100
  Entry:        $84,250.00
  ...
  ============================================================
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg
from models.ensemble import Decision

DIVIDER = '=' * 60


def _ts() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _fmt_price(p: float) -> str:
    if p >= 1000:
        return f"${p:,.2f}"
    elif p >= 1:
        return f"${p:.4f}"
    else:
        return f"${p:.6f}"


def _pct(a: float, b: float) -> str:
    """Percent change from b to a."""
    if b == 0:
        return "N/A"
    return f"{(a - b) / b * 100:+.2f}%"


def _write(text: str) -> None:
    """Write to stdout and optionally append to alerts.log."""
    print(text)
    if cfg.ALERT_LOG_FILE:
        try:
            with open(cfg.ALERT_LOG_FILE, 'a') as f:
                f.write(text + '\n')
        except OSError:
            pass


def emit_decision(symbol: str, decision: Decision) -> None:
    """
    Format and emit a full Decision alert.
    Also writes machine-readable JSON to signals/latest.json.
    """
    ts = _ts()
    lines = [DIVIDER]

    if decision.is_trade:
        lines.append(f"  QUANT SIGNAL: {symbol}  [{decision.action}]")
    else:
        lines.append(f"  QUANT: {symbol}  [NO TRADE]")
    lines.append(f"  {ts}")
    lines.append(DIVIDER)

    if decision.is_trade:
        sl_pct  = _pct(decision.stop_loss,   decision.entry)
        tp_pct  = _pct(decision.take_profit, decision.entry)
        lines += [
            f"Confidence:    {decision.confidence:.0f}/100",
            f"Entry:         {_fmt_price(decision.entry)}",
            f"Stop Loss:     {_fmt_price(decision.stop_loss)}  ({sl_pct})",
            f"Take Profit:   {_fmt_price(decision.take_profit)}  ({tp_pct})",
            f"Kelly Size:    {decision.kelly_fraction:.3f}  (fraction of capital)",
            "",
            f"Regime:        {decision.regime}",
            f"Strategy:      {decision.strategy.upper().replace('_', ' ')} "
            f"({len(decision.conditions_met)}/{'5' if decision.strategy == 'trend' else '4'} conditions)",
            f"Score:         {decision.score}/100",
            f"ML Prob:       {decision.ml_prob:.2f}",
        ]

        if decision.score_breakdown:
            lines.append("")
            lines.append("Score Breakdown:")
            for key, val in decision.score_breakdown.items():
                if key in ('total', 'rr_ratio'):
                    continue
                label = key.replace('_', ' ').title()
                lines.append(f"  {label:<22} {val}")

        if decision.conditions_met:
            lines.append("")
            lines.append("Conditions Met:")
            for c in decision.conditions_met:
                lines.append(f"  ✓ {c}")
    else:
        lines.append(f"Reason:  {decision.reject_reason}")
        lines.append(f"Regime:  {decision.regime}")

    lines.append(DIVIDER)

    _write('\n'.join(lines))
    _save_json(symbol, decision, ts)


def emit_no_trade(symbol: str, reason: str, regime: str) -> None:
    """Emit a minimal NO TRADE notice (info level, no alert log entry)."""
    ts = _ts()
    print(f"[{ts}] {symbol}: NO TRADE — {reason} (regime={regime})")


def emit_info(msg: str) -> None:
    ts = _ts()
    print(f"[{ts}] {msg}")


def emit_error(context: str, err: Exception) -> None:
    ts = _ts()
    print(f"[{ts}] ERROR [{context}]: {err}", file=sys.stderr)


def _save_json(symbol: str, decision: Decision, ts: str) -> None:
    """Save latest signal to a JSON file for Node.js integration."""
    signal_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'signals')
    os.makedirs(signal_dir, exist_ok=True)
    payload = {
        'timestamp': ts,
        'symbol': symbol,
        'action': decision.action,
        'confidence': decision.confidence,
        'entry': decision.entry,
        'stop_loss': decision.stop_loss,
        'take_profit': decision.take_profit,
        'kelly_fraction': decision.kelly_fraction,
        'regime': decision.regime,
        'strategy': decision.strategy,
        'score': decision.score,
        'ml_prob': decision.ml_prob,
        'conditions_met': decision.conditions_met,
        'reject_reason': decision.reject_reason,
    }
    path = os.path.join(signal_dir, 'latest.json')
    try:
        with open(path, 'w') as f:
            json.dump(payload, f, indent=2)
    except OSError:
        pass
