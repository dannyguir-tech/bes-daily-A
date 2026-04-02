"""
db.py — SQLite persistence layer for quantitative signals.

Stores signal history keyed by (symbol, timeframe, timestamp).
Python writes via sqlite3 (stdlib), Node.js reads via better-sqlite3.
Uses WAL mode for concurrent read/write support.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone

import sys
sys.path.insert(0, os.path.dirname(__file__))
import config as cfg

DB_PATH = os.getenv('DB_PATH', os.path.join(os.path.dirname(__file__), '..', 'data', 'signals.db'))

_conn: sqlite3.Connection | None = None


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = sqlite3.connect(DB_PATH, timeout=10)
        _conn.execute('PRAGMA journal_mode=WAL')
        _conn.execute('PRAGMA busy_timeout=5000')
        _conn.row_factory = sqlite3.Row
    return _conn


def init_db() -> None:
    """Create the signals table and indexes if they don't exist."""
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol          TEXT    NOT NULL,
            timeframe       TEXT    NOT NULL,
            timestamp       TEXT    NOT NULL,
            action          TEXT    NOT NULL,
            confidence      REAL    DEFAULT 0,
            entry           REAL    DEFAULT 0,
            stop_loss       REAL    DEFAULT 0,
            take_profit     REAL    DEFAULT 0,
            kelly_fraction  REAL    DEFAULT 0,
            regime          TEXT    DEFAULT '',
            strategy        TEXT    DEFAULT '',
            score           INTEGER DEFAULT 0,
            ml_prob         REAL    DEFAULT 0,
            conditions_met  TEXT    DEFAULT '[]',
            reject_reason   TEXT    DEFAULT '',
            score_breakdown TEXT    DEFAULT '{}',
            created_at      TEXT    DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
        );
        CREATE INDEX IF NOT EXISTS idx_signals_tf
            ON signals(timeframe);
        CREATE INDEX IF NOT EXISTS idx_signals_symbol_tf
            ON signals(symbol, timeframe);
        CREATE INDEX IF NOT EXISTS idx_signals_ts
            ON signals(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_signals_action
            ON signals(action);
    """)
    conn.commit()


def insert_signal(symbol: str, timeframe: str, action: str, confidence: float = 0,
                  entry: float = 0, stop_loss: float = 0, take_profit: float = 0,
                  kelly_fraction: float = 0, regime: str = '', strategy: str = '',
                  score: int = 0, ml_prob: float = 0, conditions_met: list = None,
                  reject_reason: str = '', score_breakdown: dict = None,
                  timestamp: str = None) -> int:
    """Insert a signal row. Returns the row id."""
    conn = _get_conn()
    if timestamp is None:
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    cur = conn.execute("""
        INSERT INTO signals
            (symbol, timeframe, timestamp, action, confidence, entry, stop_loss,
             take_profit, kelly_fraction, regime, strategy, score, ml_prob,
             conditions_met, reject_reason, score_breakdown)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        symbol, timeframe, timestamp, action, confidence, entry, stop_loss,
        take_profit, kelly_fraction, regime, strategy, score, ml_prob,
        json.dumps(conditions_met or []),
        reject_reason,
        json.dumps(score_breakdown or {}),
    ))
    conn.commit()
    return cur.lastrowid


def get_signals(timeframe: str = None, symbol: str = None, limit: int = 50,
                action_filter: bool = True) -> list[dict]:
    """
    Query signals with optional filters.
    action_filter=True returns only BUY/SELL (excludes NO TRADE).
    """
    conn = _get_conn()
    clauses = []
    params = []
    if action_filter:
        clauses.append("action IN ('BUY', 'SELL')")
    if timeframe:
        clauses.append("timeframe = ?")
        params.append(timeframe)
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM signals {where} ORDER BY timestamp DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    return [dict(r) for r in rows]


def get_counts_by_timeframe() -> dict[str, int]:
    """Return signal counts per timeframe (BUY/SELL only)."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT timeframe, COUNT(*) as cnt
        FROM signals
        WHERE action IN ('BUY', 'SELL')
        GROUP BY timeframe
    """).fetchall()
    return {r['timeframe']: r['cnt'] for r in rows}


def get_latest_per_symbol(timeframe: str = None) -> list[dict]:
    """Most recent signal per symbol, optionally filtered by timeframe."""
    conn = _get_conn()
    tf_clause = "AND timeframe = ?" if timeframe else ""
    params = [timeframe] if timeframe else []
    rows = conn.execute(f"""
        SELECT s.* FROM signals s
        INNER JOIN (
            SELECT symbol, MAX(timestamp) as max_ts
            FROM signals
            WHERE action IN ('BUY', 'SELL')
            {tf_clause}
            GROUP BY symbol
        ) latest ON s.symbol = latest.symbol AND s.timestamp = latest.max_ts
        ORDER BY s.timestamp DESC
    """, params).fetchall()
    return [dict(r) for r in rows]
