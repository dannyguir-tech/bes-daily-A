/**
 * server.js — Express dashboard server for BES Quant Signals.
 *
 * Reads signal data from SQLite (written by Python quant engine).
 * Serves REST API + static frontend dashboard.
 *
 * Usage:
 *   npm run dashboard          # start on port 3000
 *   DASHBOARD_PORT=8080 npm run dashboard
 */

import 'dotenv/config';
import express from 'express';
import Database from 'better-sqlite3';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PORT = parseInt(process.env.DASHBOARD_PORT || '3000', 10);
const DB_PATH = process.env.DB_PATH || join(__dirname, '..', 'data', 'signals.db');

// ─── Database ─────────────────────────────────────────────────────────────────

let db;
try {
  db = new Database(DB_PATH, { readonly: true, fileMustExist: true });
  db.pragma('journal_mode = WAL');
} catch {
  // DB doesn't exist yet — create it so the dashboard can start even before
  // the Python engine has run. Use a writable connection to init the schema.
  const initDb = new Database(DB_PATH);
  initDb.exec(`
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
    CREATE INDEX IF NOT EXISTS idx_signals_tf ON signals(timeframe);
    CREATE INDEX IF NOT EXISTS idx_signals_symbol_tf ON signals(symbol, timeframe);
    CREATE INDEX IF NOT EXISTS idx_signals_ts ON signals(timestamp DESC);
    CREATE INDEX IF NOT EXISTS idx_signals_action ON signals(action);
  `);
  initDb.pragma('journal_mode = WAL');
  initDb.close();
  db = new Database(DB_PATH, { readonly: true });
}

// Prepared statements
const stmtCounts = db.prepare(`
  SELECT timeframe, COUNT(*) as cnt
  FROM signals
  WHERE action IN ('BUY', 'SELL')
  GROUP BY timeframe
`);

const stmtAllCount = db.prepare(`
  SELECT COUNT(*) as cnt FROM signals WHERE action IN ('BUY', 'SELL')
`);

// ─── Helpers ──────────────────────────────────────────────────────────────────

function parseRow(row) {
  return {
    ...row,
    conditions_met: JSON.parse(row.conditions_met || '[]'),
    score_breakdown: JSON.parse(row.score_breakdown || '{}'),
  };
}

// ─── Express App ──────────────────────────────────────────────────────────────

const app = express();

// Serve static dashboard files
app.use(express.static(join(__dirname, '..', 'public')));

// API: signal counts per timeframe (for sidebar badges)
app.get('/api/signals/counts', (_req, res) => {
  const rows = stmtCounts.all();
  const counts = {};
  let total = 0;
  for (const r of rows) {
    counts[r.timeframe] = r.cnt;
    total += r.cnt;
  }
  counts.all = total;
  res.json(counts);
});

// API: query signals with optional filters
app.get('/api/signals', (req, res) => {
  const { timeframe, symbol, limit = '50' } = req.query;
  const clauses = ["action IN ('BUY', 'SELL')"];
  const params = [];

  if (timeframe && timeframe !== 'all') {
    clauses.push('timeframe = ?');
    params.push(timeframe);
  }
  if (symbol) {
    clauses.push('symbol = ?');
    params.push(symbol);
  }

  const lim = Math.min(parseInt(limit, 10) || 50, 200);
  params.push(lim);

  const where = clauses.length ? `WHERE ${clauses.join(' AND ')}` : '';
  const rows = db.prepare(
    `SELECT * FROM signals ${where} ORDER BY timestamp DESC LIMIT ?`
  ).all(...params);

  res.json({
    signals: rows.map(parseRow),
    total: rows.length,
  });
});

// API: latest signal per symbol
app.get('/api/signals/latest', (req, res) => {
  const { timeframe } = req.query;
  let query;
  const params = [];

  if (timeframe && timeframe !== 'all') {
    query = `
      SELECT s.* FROM signals s
      INNER JOIN (
        SELECT symbol, MAX(timestamp) as max_ts
        FROM signals
        WHERE action IN ('BUY', 'SELL') AND timeframe = ?
        GROUP BY symbol
      ) latest ON s.symbol = latest.symbol AND s.timestamp = latest.max_ts
      ORDER BY s.timestamp DESC
    `;
    params.push(timeframe);
  } else {
    query = `
      SELECT s.* FROM signals s
      INNER JOIN (
        SELECT symbol, MAX(timestamp) as max_ts
        FROM signals
        WHERE action IN ('BUY', 'SELL')
        GROUP BY symbol
      ) latest ON s.symbol = latest.symbol AND s.timestamp = latest.max_ts
      ORDER BY s.timestamp DESC
    `;
  }

  const rows = db.prepare(query).all(...params);
  res.json({ signals: rows.map(parseRow) });
});

// API: health check
app.get('/api/health', (_req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// ─── Start Server ─────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`Dashboard server running at http://localhost:${PORT}`);
  console.log(`SQLite DB: ${DB_PATH}`);
});
