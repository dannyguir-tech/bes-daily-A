/**
 * indicators/analyzer.js — Multi-timeframe technical analysis orchestrator.
 *
 * Pulls candles from SQLite for all 7 timeframes, runs indicator analysis
 * on each, and returns a unified result object.
 */

import { getCandles, getCandleCount } from '../db/storage.js';
import { SYMBOL, TIMEFRAMES } from '../data/fetcher.js';
import { analyzeTimeframe } from './technical.js';
import { generateMockCandles } from './mockData.js';
import logger from '../logger.js';

const MIN_CANDLES = 30;

/**
 * Run technical analysis across all timeframes.
 * Falls back to mock data if a timeframe has fewer than 30 candles.
 *
 * @returns {Object} Analysis results keyed by timeframe
 */
export async function analyzeAllTimeframes() {
  const results = {};

  for (const tf of TIMEFRAMES) {
    const count = getCandleCount(SYMBOL, tf);

    let candles;
    if (count >= MIN_CANDLES) {
      candles = getCandles(SYMBOL, tf, 200);
      logger.info(`${tf}: analyzing ${candles.length} candles from database`);
    } else {
      logger.warn(`${tf}: only ${count} candle(s) in DB, using mock data (200 candles)`);
      candles = generateMockCandles(200);
    }

    const analysis = analyzeTimeframe(candles, tf);
    if (analysis) {
      results[tf] = analysis;
    }
  }

  return results;
}
