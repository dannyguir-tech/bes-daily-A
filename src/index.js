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
import { analyzeAllWithClaude } from './analysis/claude.js';
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

  // 6. Claude AI analysis
  if (process.env.ANTHROPIC_API_KEY) {
    logger.info('');
    logger.info('═'.repeat(60));
    logger.info('  CLAUDE AI ANALYSIS');
    logger.info('═'.repeat(60));

    try {
      // Gather raw candles for each timeframe (for the prompt)
      const allCandles = {};
      for (const tf of TIMEFRAMES) {
        const c = getCandles(SYMBOL, tf, 50);
        if (c.length > 0) {
          allCandles[tf] = c;
        }
      }

      // If no real candles, use mock data via the analysis object
      // (analysis already has mock-based indicators from step 5)
      if (Object.keys(allCandles).length === 0) {
        logger.warn('No candles in DB for Claude prompt — using mock candle data');
        const { generateMockCandles } = await import('./indicators/mockData.js');
        for (const tf of TIMEFRAMES) {
          allCandles[tf] = generateMockCandles(50);
        }
      }

      const claudeResults = await analyzeAllWithClaude(allCandles, analysis);

      if (Object.keys(claudeResults).length > 0) {
        logger.info(
          '  ' +
          'TF'.padEnd(5) +
          'Direction'.padEnd(11) +
          'Conf'.padStart(6) +
          'Score'.padStart(8) +
          '  Patterns'.padEnd(22) +
          'Reasoning'
        );
        logger.info('  ' + '─'.repeat(80));

        for (const tf of TIMEFRAMES) {
          const cr = claudeResults[tf];
          if (!cr) continue;

          const patterns = cr.patterns_detected?.length > 0
            ? cr.patterns_detected.slice(0, 2).join(', ')
            : '—';

          const reasoning = cr.reasoning?.length > 40
            ? cr.reasoning.slice(0, 40) + '...'
            : cr.reasoning || '—';

          logger.info(
            '  ' +
            tf.padEnd(5) +
            cr.direction.padEnd(11) +
            (cr.confidence + '%').padStart(6) +
            (cr.score >= 0 ? '+' : '').concat(cr.score.toFixed(2)).padStart(8) +
            ('  ' + patterns).padEnd(22) +
            reasoning
          );
        }

        // Print key levels if available
        const hasLevels = TIMEFRAMES.some(tf =>
          claudeResults[tf]?.key_support || claudeResults[tf]?.key_resistance
        );
        if (hasLevels) {
          logger.info('');
          logger.info('  Key Levels:');
          for (const tf of TIMEFRAMES) {
            const cr = claudeResults[tf];
            if (!cr?.key_support && !cr?.key_resistance) continue;
            const s = cr.key_support ? `$${cr.key_support.toFixed(2)}` : 'N/A';
            const r = cr.key_resistance ? `$${cr.key_resistance.toFixed(2)}` : 'N/A';
            logger.info(`  ${tf.padEnd(5)} Support: ${s}  |  Resistance: ${r}`);
          }
        }
      } else {
        logger.warn('  Claude analysis returned no results.');
      }
    } catch (err) {
      logger.error(`  Claude analysis failed: ${err.message}`);
    }
  } else {
    logger.info('');
    logger.warn('ANTHROPIC_API_KEY not set — skipping Claude AI analysis.');
    logger.warn('Add it to your .env file to enable AI-powered insights.');
  }

  logger.info('');
  logger.info('Done.');
}

main().catch((err) => {
  logger.error(`Fatal: ${err.message}`);
  process.exit(1);
});
