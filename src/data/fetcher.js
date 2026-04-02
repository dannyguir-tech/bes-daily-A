/**
 * data/fetcher.js — OHLCV candle fetching via ccxt.
 *
 * Fetches BTC/USDT candles from Binance for all timeframes.
 * Uses binance.us as fallback if binance is geo-restricted.
 * Supports incremental fetching (only new candles since last stored).
 */

import ccxt from 'ccxt';
import { getLatestTimestamp, insertCandles } from '../db/storage.js';
import logger from '../logger.js';

const SYMBOL = 'BTC/USDT';
const TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d', '1w', '1M'];
const SEED_LIMIT = 200;
const RATE_LIMIT_MS = 1000; // 1 second between timeframe fetches

let exchange = null;

/**
 * Initialize the ccxt exchange instance.
 * Tries Binance first, falls back to Binance US.
 */
async function initExchange() {
  if (exchange) return exchange;

  // Try exchanges in order of preference
  const exchanges = [
    { id: 'binance', Class: ccxt.binance, name: 'Binance' },
    { id: 'binanceus', Class: ccxt.binanceus, name: 'Binance US' },
    { id: 'bybit', Class: ccxt.bybit, name: 'Bybit' },
    { id: 'kraken', Class: ccxt.kraken, name: 'Kraken' },
    { id: 'coinbase', Class: ccxt.coinbase, name: 'Coinbase' },
  ];

  for (const { Class, name } of exchanges) {
    try {
      const ex = new Class({ enableRateLimit: true, timeout: 15000 });
      await ex.loadMarkets();
      // Verify the symbol exists on this exchange
      if (!ex.markets[SYMBOL]) {
        logger.warn(`${name}: ${SYMBOL} not available, trying next...`);
        continue;
      }
      exchange = ex;
      logger.info(`Connected to ${name}`);
      return exchange;
    } catch (err) {
      logger.warn(`${name} failed (${err.message}), trying next...`);
    }
  }

  throw new Error('Failed to connect to any exchange');
}

/**
 * Sleep for a given number of milliseconds.
 */
function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Fetch candles for a single timeframe, storing new ones in SQLite.
 *
 * @param {string} timeframe  e.g. '5m', '1h', '1d'
 * @returns {number} Number of new candles stored
 */
async function fetchTimeframe(timeframe) {
  const ex = await initExchange();

  // Check what we already have
  const latestTs = getLatestTimestamp(SYMBOL, timeframe);

  let candles;
  if (latestTs) {
    // Incremental: fetch candles AFTER the last one we have
    // Add 1ms to avoid re-fetching the exact same candle
    const since = latestTs + 1;
    logger.info(`${timeframe}: fetching candles since ${new Date(since).toISOString()}`);
    candles = await ex.fetchOHLCV(SYMBOL, timeframe, since, SEED_LIMIT);
  } else {
    // Initial seed: fetch last 200 candles
    logger.info(`${timeframe}: no existing data, seeding last ${SEED_LIMIT} candles`);
    candles = await ex.fetchOHLCV(SYMBOL, timeframe, undefined, SEED_LIMIT);
  }

  if (!candles || candles.length === 0) {
    logger.info(`${timeframe}: no new candles available`);
    return 0;
  }

  // ccxt returns [timestamp, open, high, low, close, volume]
  const inserted = insertCandles(SYMBOL, timeframe, candles);
  logger.info(`${timeframe}: fetched ${candles.length}, stored ${inserted} new candle(s)`);

  return inserted;
}

/**
 * Fetch all timeframes sequentially with rate limiting.
 *
 * @returns {{ totalCandles: number, timeframesFetched: number, results: Object }}
 */
export async function fetchAllTimeframes() {
  await initExchange();

  let totalCandles = 0;
  let timeframesFetched = 0;
  const results = {};

  for (const tf of TIMEFRAMES) {
    try {
      const count = await fetchTimeframe(tf);
      results[tf] = { success: true, newCandles: count };
      totalCandles += count;
      timeframesFetched++;
    } catch (err) {
      logger.error(`${tf}: fetch failed — ${err.message}`);
      results[tf] = { success: false, error: err.message };
    }

    // Rate limit between timeframe fetches
    if (tf !== TIMEFRAMES[TIMEFRAMES.length - 1]) {
      await sleep(RATE_LIMIT_MS);
    }
  }

  return { totalCandles, timeframesFetched, results };
}

export { SYMBOL, TIMEFRAMES };
