/**
 * indicators/technical.js — Technical indicator computation and scoring.
 *
 * Computes RSI, MACD, EMA, Bollinger Bands, ATR, and Volume SMA from
 * OHLCV candle data using the technicalindicators library.
 *
 * Scores each indicator from -1.0 (strong bearish) to +1.0 (strong bullish),
 * then produces a weighted combined score and signal label.
 */

import { RSI, MACD, EMA, BollingerBands, ATR, SMA } from 'technicalindicators';
import logger from '../logger.js';

// ─── Data Preparation ───────────────────────────────────────────────────────

/**
 * Reverse candles to chronological order and extract parallel arrays.
 * getCandles() returns DESC (newest first); indicators need ASC (oldest first).
 */
function prepareCandles(candles) {
  const sorted = [...candles].reverse();
  return {
    sorted,
    closes: sorted.map(c => c.close),
    highs: sorted.map(c => c.high),
    lows: sorted.map(c => c.low),
    volumes: sorted.map(c => c.volume),
  };
}

/**
 * Safely get the last element of an array, or null.
 */
function last(arr) {
  return arr && arr.length > 0 ? arr[arr.length - 1] : null;
}

/**
 * Safely get the second-to-last element, or null.
 */
function secondLast(arr) {
  return arr && arr.length > 1 ? arr[arr.length - 2] : null;
}

// ─── Indicator Computation ──────────────────────────────────────────────────

/**
 * Compute all raw indicators from OHLCV arrays.
 */
function computeIndicators(closes, highs, lows, volumes) {
  // RSI(14)
  const rsiValues = RSI.calculate({ values: closes, period: 14 });

  // MACD(12, 26, 9)
  const macdValues = MACD.calculate({
    values: closes,
    fastPeriod: 12,
    slowPeriod: 26,
    signalPeriod: 9,
    SimpleMAOscillator: false,
    SimpleMASignal: false,
  });

  // EMA 20, 50, 200
  const ema20Values = EMA.calculate({ values: closes, period: 20 });
  const ema50Values = EMA.calculate({ values: closes, period: 50 });
  const ema200Values = closes.length >= 200
    ? EMA.calculate({ values: closes, period: 200 })
    : null;

  // Bollinger Bands (20, 2)
  const bbValues = BollingerBands.calculate({
    values: closes,
    period: 20,
    stdDev: 2,
  });

  // ATR(14)
  const atrValues = ATR.calculate({
    high: highs,
    low: lows,
    close: closes,
    period: 14,
  });

  // Volume SMA(20)
  const volSmaValues = SMA.calculate({ values: volumes, period: 20 });

  // Extract latest values
  const latestClose = closes[closes.length - 1];
  const latestVolume = volumes[volumes.length - 1];
  const bb = last(bbValues);

  // Compute percentB manually
  let percentB = null;
  if (bb) {
    const bandwidth = bb.upper - bb.lower;
    percentB = bandwidth > 0 ? (latestClose - bb.lower) / bandwidth : 0.5;
  }

  return {
    rsi: last(rsiValues) ?? null,
    macd: last(macdValues) ?? null,
    macdPrev: secondLast(macdValues) ?? null,
    ema20: last(ema20Values) ?? null,
    ema50: last(ema50Values) ?? null,
    ema200: ema200Values ? last(ema200Values) : null,
    hasEma200: ema200Values !== null && ema200Values.length > 0,
    bb: bb ?? null,
    percentB,
    atr: last(atrValues) ?? null,
    volumeSma: last(volSmaValues) ?? null,
    latestClose,
    latestVolume,
  };
}

// ─── Scoring Functions ──────────────────────────────────────────────────────

/**
 * Score RSI from -1.0 (overbought/bearish) to +1.0 (oversold/bullish).
 * Uses linear interpolation within zones.
 */
function scoreRSI(rsi) {
  if (rsi === null || rsi === undefined || isNaN(rsi)) return 0;

  if (rsi <= 20) return 1.0;
  if (rsi <= 30) return 1.0 - 0.5 * (rsi - 20) / 10;
  if (rsi <= 45) return 0.5 - 0.5 * (rsi - 30) / 15;
  if (rsi <= 55) return 0;
  if (rsi <= 70) return -0.5 * (rsi - 55) / 15;
  if (rsi <= 80) return -0.5 - 0.5 * (rsi - 70) / 10;
  return -1.0;
}

/**
 * Score MACD from -1.0 to +1.0.
 * 60% histogram direction, 40% crossover detection.
 */
function scoreMACD(macd, macdPrev) {
  if (!macd || macd.MACD === undefined) return 0;

  // Histogram direction score (60% weight)
  let histScore = 0;
  if (macd.histogram !== undefined && macd.histogram !== null) {
    const direction = macd.histogram > 0 ? 1.0 : -1.0;
    const signalAbs = Math.abs(macd.signal || 1);
    const magnitude = Math.min(Math.abs(macd.histogram) / signalAbs, 1.0);
    histScore = direction * magnitude;
  }

  // Crossover detection (40% weight)
  let crossScore = 0;
  if (macdPrev && macdPrev.MACD !== undefined && macdPrev.signal !== undefined) {
    const prevDiff = macdPrev.MACD - macdPrev.signal;
    const currDiff = macd.MACD - macd.signal;
    if (prevDiff <= 0 && currDiff > 0) crossScore = 1.0;   // bullish cross
    else if (prevDiff >= 0 && currDiff < 0) crossScore = -1.0; // bearish cross
  }

  const score = 0.6 * histScore + 0.4 * crossScore;
  return Math.max(-1, Math.min(1, score));
}

/**
 * Score EMA alignment from -1.0 to +1.0.
 * 50% price position relative to EMAs, 50% EMA order alignment.
 */
function scoreEMA(latestClose, ema20, ema50, ema200) {
  // Collect available EMAs
  const emas = [];
  if (ema20 !== null && ema20 !== undefined) emas.push({ name: 'ema20', value: ema20 });
  if (ema50 !== null && ema50 !== undefined) emas.push({ name: 'ema50', value: ema50 });
  if (ema200 !== null && ema200 !== undefined) emas.push({ name: 'ema200', value: ema200 });

  if (emas.length === 0) return 0;

  // Price position score (50%): how many EMAs is price above?
  const aboveCount = emas.filter(e => latestClose > e.value).length;
  const positionScore = (aboveCount / emas.length) * 2 - 1;

  // EMA alignment score (50%)
  let alignmentScore = 0;
  if (emas.length === 3) {
    if (ema20 > ema50 && ema50 > ema200) alignmentScore = 1.0;       // bullish order
    else if (ema20 < ema50 && ema50 < ema200) alignmentScore = -1.0;  // bearish order
  } else if (emas.length === 2 && ema20 !== null && ema50 !== null) {
    if (ema20 > ema50) alignmentScore = 0.7;
    else if (ema20 < ema50) alignmentScore = -0.7;
  }

  return 0.5 * positionScore + 0.5 * alignmentScore;
}

/**
 * Score Bollinger Bands position.
 * Lower band (percentB=0) → +1.0 (oversold), upper (percentB=1) → -1.0 (overbought).
 */
function scoreBollinger(percentB) {
  if (percentB === null || percentB === undefined || isNaN(percentB)) return 0;
  return Math.max(-1, Math.min(1, 1.0 - 2.0 * percentB));
}

/**
 * Compute volume confirmation modifier.
 * Above average volume → 1.2x amplification, below → 0.8x dampening.
 */
function computeVolumeModifier(latestVolume, volumeSma) {
  if (!volumeSma || volumeSma === 0 || !latestVolume) return 1.0;
  return latestVolume >= volumeSma ? 1.2 : 0.8;
}

// ─── Combined Score ─────────────────────────────────────────────────────────

/**
 * Compute weighted combined score from individual indicator scores.
 */
function computeCombinedScore(indicators) {
  const scores = {
    rsi: scoreRSI(indicators.rsi),
    macd: scoreMACD(indicators.macd, indicators.macdPrev),
    ema: scoreEMA(indicators.latestClose, indicators.ema20, indicators.ema50, indicators.ema200),
    bollinger: scoreBollinger(indicators.percentB),
    volumeModifier: computeVolumeModifier(indicators.latestVolume, indicators.volumeSma),
  };

  // Adjust weights based on EMA200 availability
  const weights = indicators.hasEma200
    ? { rsi: 0.25, macd: 0.25, ema: 0.25, bb: 0.15 }
    : { rsi: 0.30, macd: 0.30, ema: 0.20, bb: 0.20 };

  let combined = (
    weights.rsi * scores.rsi +
    weights.macd * scores.macd +
    weights.ema * scores.ema +
    weights.bb * scores.bollinger
  );

  // Apply volume modifier
  combined *= scores.volumeModifier;

  // Clamp to [-1, +1]
  combined = Math.max(-1, Math.min(1, combined));

  return { scores, combined };
}

/**
 * Convert a numeric score to a signal label.
 */
function getSignal(score) {
  if (score > 0.7) return 'STRONG_BUY';
  if (score > 0.4) return 'BUY';
  if (score > -0.4) return 'NEUTRAL';
  if (score > -0.7) return 'SELL';
  return 'STRONG_SELL';
}

// ─── Main Export ────────────────────────────────────────────────────────────

/**
 * Analyze a set of candles and produce indicator scores + signal.
 *
 * @param {Array} candles   Array of {timestamp, open, high, low, close, volume} — DESC order
 * @param {string} timeframe  Timeframe label (e.g. '1h')
 * @returns {Object|null} Analysis result or null if insufficient data
 */
export function analyzeTimeframe(candles, timeframe) {
  if (!candles || candles.length < 30) {
    logger.warn(`${timeframe}: insufficient candles (${candles?.length ?? 0}), need at least 30`);
    return null;
  }

  const { closes, highs, lows, volumes } = prepareCandles(candles);
  const indicators = computeIndicators(closes, highs, lows, volumes);
  const { scores, combined } = computeCombinedScore(indicators);
  const signal = getSignal(combined);

  return {
    timeframe,
    timestamp: Date.now(),
    raw: {
      rsi: indicators.rsi,
      macd: indicators.macd ? {
        line: indicators.macd.MACD,
        signal: indicators.macd.signal,
        histogram: indicators.macd.histogram,
      } : null,
      ema: {
        ema20: indicators.ema20,
        ema50: indicators.ema50,
        ema200: indicators.ema200,
      },
      bollinger: indicators.bb ? {
        upper: indicators.bb.upper,
        middle: indicators.bb.middle,
        lower: indicators.bb.lower,
        percentB: indicators.percentB,
      } : null,
      atr: indicators.atr,
      volume: {
        current: indicators.latestVolume,
        sma20: indicators.volumeSma,
        aboveAverage: indicators.latestVolume >= (indicators.volumeSma ?? 0),
      },
    },
    scores: {
      rsi: scores.rsi,
      macd: scores.macd,
      ema: scores.ema,
      bollinger: scores.bollinger,
      volumeModifier: scores.volumeModifier,
    },
    combinedScore: combined,
    signal,
  };
}
