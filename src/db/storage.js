/**
 * db/storage.js — SQLite setup, table creation, insert/query helpers.
 *
 * Uses better-sqlite3 for synchronous, fast SQLite access.
 * Database file: ./data/bot.db
 */

import Database from 'better-sqlite3';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';
import { mkdirSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const DB_PATH = join(__dirname, '..', '..', 'data', 'bot.db');

let db;

/**
 * Initialize the database — create tables if they don't exist.
 * @returns {Database} The database instance
 */
export function initDatabase() {
  mkdirSync(dirname(DB_PATH), { recursive: true });

  db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  db.pragma('busy_timeout = 5000');

  db.exec(`
    CREATE TABLE IF NOT EXISTS candles (
      id        INTEGER PRIMARY KEY AUTOINCREMENT,
      symbol    TEXT    NOT NULL DEFAULT 'BTC/USDT',
      timeframe TEXT    NOT NULL,
      timestamp INTEGER NOT NULL,
      open      REAL    NOT NULL,
      high      REAL    NOT NULL,
      low       REAL    NOT NULL,
      close     REAL    NOT NULL,
      volume    REAL    NOT NULL,
      UNIQUE(symbol, timeframe, timestamp)
    );
    CREATE INDEX IF NOT EXISTS idx_candles_sym_tf_ts
      ON candles(symbol, timeframe, timestamp DESC);
  `);

  return db;
}

/**
 * Bulk insert candles, skipping duplicates.
 * @param {string}   symbol     e.g. 'BTC/USDT'
 * @param {string}   timeframe  e.g. '5m', '1h', '1d'
 * @param {Array}    candles    Array of [timestamp, open, high, low, close, volume]
 * @returns {number} Number of candles actually inserted (new ones)
 */
export function insertCandles(symbol, timeframe, candles) {
  if (!candles || candles.length === 0) return 0;

  const stmt = db.prepare(`
    INSERT OR IGNORE INTO candles (symbol, timeframe, timestamp, open, high, low, close, volume)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
  `);

  const insertMany = db.transaction((rows) => {
    let inserted = 0;
    for (const row of rows) {
      const [ts, open, high, low, close, volume] = row;
      const result = stmt.run(symbol, timeframe, ts, open, high, low, close, volume);
      if (result.changes > 0) inserted++;
    }
    return inserted;
  });

  return insertMany(candles);
}

/**
 * Get the most recent candle timestamp we have for a symbol+timeframe.
 * @param {string} symbol
 * @param {string} timeframe
 * @returns {number|null} Unix timestamp in ms, or null if no data
 */
export function getLatestTimestamp(symbol, timeframe) {
  const row = db.prepare(`
    SELECT MAX(timestamp) as latest
    FROM candles
    WHERE symbol = ? AND timeframe = ?
  `).get(symbol, timeframe);

  return row?.latest ?? null;
}

/**
 * Get the most recent N candles for a symbol+timeframe.
 * @param {string} symbol
 * @param {string} timeframe
 * @param {number} limit
 * @returns {Array} Array of candle objects, newest first
 */
export function getCandles(symbol, timeframe, limit = 200) {
  return db.prepare(`
    SELECT timestamp, open, high, low, close, volume
    FROM candles
    WHERE symbol = ? AND timeframe = ?
    ORDER BY timestamp DESC
    LIMIT ?
  `).all(symbol, timeframe, limit);
}

/**
 * Get total candle count for a symbol+timeframe.
 * @param {string} symbol
 * @param {string} timeframe
 * @returns {number}
 */
export function getCandleCount(symbol, timeframe) {
  const row = db.prepare(`
    SELECT COUNT(*) as cnt
    FROM candles
    WHERE symbol = ? AND timeframe = ?
  `).get(symbol, timeframe);

  return row?.cnt ?? 0;
}
