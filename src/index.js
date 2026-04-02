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
import logger from './logger.js';

async function main() {
  // 1. Initialize the database
  logger.info('Initializing database...');
  initDatabase();
  logger.info('Database ready.');

  // 2. Fetch candles for all timeframes
  logger.info(`Fetching ${SYMBOL} candles across ${TIMEFRAMES.length} timeframes: ${TIMEFRAMES.join(', ')}`);
  const { totalCandles, timeframesFetched, results } = await fetchAllTimeframes();

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
    } else {
      logger.error(`  ${tf.padEnd(4)} — FAILED: ${r?.error ?? 'unknown error'}`);
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

  logger.info('');
  logger.info('Done.');
}

main().catch((err) => {
  logger.error(`Fatal: ${err.message}`);
  process.exit(1);
});
