/**
 * BES Daily-A — Entry point
 *
 * Initializes the database, fetches OHLCV candles for all timeframes,
 * and prints the latest candle per timeframe for verification.
 *
 * Usage:
 *   node src/index.js
 */

import 'dotenv/config';
import { initDatabase, getCandles, getCandleCount } from './db/storage.js';
import { fetchAllTimeframes, SYMBOL, TIMEFRAMES } from './data/fetcher.js';
import { analyzeAllTimeframes } from './indicators/analyzer.js';
import logger from './logger.js';

async function main() {
  // 1. Initialize the database
  logger.info('Initializing database...');
  initDatabase();
  logger.info('Database ready.');

  // 2. Fetch candles for all timeframes
  logger.info(`Fetching ${SYMBOL} candles across ${TIMEFRAMES.length} timeframes: ${TIMEFRAMES.join(', ')}`);
  let fetchResult = { totalCandles: 0, timeframesFetched: 0, results: {} };
  try {
    fetchResult = await fetchAllTimeframes();
  } catch (err) {
    logger.warn(`Exchange fetch failed: ${err.message}`);
    logger.warn('Will use mock data for analysis.');
  }
  const { totalCandles, timeframesFetched, results } = fetchResult;

  // 3. Log summary
  logger.info('');
  logger.info('═'.repeat(60));
  logger.info(`  FETCH SUMMARY`);
  logger.info('═'.repeat(60));
  logger.info(`Fetched ${totalCandles} new candle(s) across ${timeframesFetched} timeframe(s)`);
  logger.info('');

  for (const tf of TIMEFRAMES) {
    const r = results[tf];
    if (r?.success) {
      logger.info(`  ${tf.padEnd(4)} — ${r.newCandles} new candle(s)`);
    } else if (r?.error) {
      logger.error(`  ${tf.padEnd(4)} — FAILED: ${r.error}`);
    }
  }

  // 4. Print the latest candle per timeframe
  logger.info('');
  logger.info('═'.repeat(60));
  logger.info('  LATEST CANDLE PER TIMEFRAME');
  logger.info('═'.repeat(60));

  for (const tf of TIMEFRAMES) {
    const candles = getCandles(SYMBOL, tf, 1);
    const total = getCandleCount(SYMBOL, tf);

    if (candles.length > 0) {
      const c = candles[0];
      const date = new Date(c.timestamp).toISOString();
      logger.info(
        `  ${tf.padEnd(4)} | ${date} | ` +
        `O: ${c.open.toFixed(2)}  H: ${c.high.toFixed(2)}  ` +
        `L: ${c.low.toFixed(2)}  C: ${c.close.toFixed(2)}  ` +
        `V: ${c.volume.toFixed(2)}  | total: ${total} candles`
      );
    } else {
      logger.warn(`  ${tf.padEnd(4)} | no data`);
    }
  }

  // 5. Run technical analysis
  logger.info('');
  logger.info('═'.repeat(60));
  logger.info('  TECHNICAL ANALYSIS');
  logger.info('═'.repeat(60));

  const analysis = await analyzeAllTimeframes();

  // Print header
  logger.info(
    '  ' +
    'TF'.padEnd(5) +
    'Score'.padStart(8) +
    '  Signal'.padEnd(14) +
    'RSI'.padStart(7) +
    'MACD'.padStart(7) +
    'EMA'.padStart(7) +
    'BB'.padStart(7) +
    'VolMod'.padStart(8)
  );
  logger.info('  ' + '─'.repeat(65));

  for (const tf of TIMEFRAMES) {
    const a = analysis[tf];
    if (!a) {
      logger.warn(`  ${tf.padEnd(4)} | analysis unavailable`);
      continue;
    }

    const fmt = (v) => v === null || v === undefined || isNaN(v)
      ? '  N/A'
      : (v >= 0 ? '+' : '') + v.toFixed(2);

    logger.info(
      '  ' +
      tf.padEnd(5) +
      fmt(a.combinedScore).padStart(8) +
      ('  ' + a.signal).padEnd(14) +
      fmt(a.scores.rsi).padStart(7) +
      fmt(a.scores.macd).padStart(7) +
      fmt(a.scores.ema).padStart(7) +
      fmt(a.scores.bollinger).padStart(7) +
      ('  ' + a.scores.volumeModifier.toFixed(1) + 'x').padStart(8)
    );
  }

  logger.info('');
  logger.info('Done.');
}

main().catch((err) => {
  logger.error(`Fatal: ${err.message}`);
  process.exit(1);
});
