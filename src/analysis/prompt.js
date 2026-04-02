/**
 * analysis/prompt.js — Prompt template builder for Claude AI analysis.
 *
 * Formats candle data and indicator results into structured prompts
 * for single-timeframe or batched multi-timeframe analysis.
 */

/**
 * Round a number to 2 decimal places. Returns 'N/A' for null/undefined.
 */
function fmt(v) {
  if (v === null || v === undefined || isNaN(v)) return 'N/A';
  return Number(v).toFixed(2);
}

/**
 * Format an array of numbers as a compact string: [n1, n2, n3, ...]
 */
function fmtArray(arr) {
  return '[' + arr.map(v => fmt(v)).join(', ') + ']';
}

/**
 * Build the data block for a single timeframe analysis.
 *
 * @param {string} timeframe  e.g. '1h'
 * @param {Array}  candles    Candle objects from getCandles() (DESC order)
 * @param {Object} indicators Result from analyzeTimeframe() with .raw and .scores
 * @returns {string} Formatted prompt data block
 */
export function buildAnalysisPrompt(timeframe, candles, indicators) {
  // Take last 50, reverse to chronological (oldest first)
  const recent = candles.slice(0, 50).reverse();

  const opens = recent.map(c => c.open);
  const highs = recent.map(c => c.high);
  const lows = recent.map(c => c.low);
  const closes = recent.map(c => c.close);
  const volumes = recent.map(c => c.volume);

  const currentPrice = recent.length > 0 ? fmt(recent[recent.length - 1].close) : 'N/A';
  const raw = indicators?.raw || {};
  const scores = indicators?.scores || {};

  const volumeRatio = (raw.volume?.sma20 && raw.volume.sma20 > 0)
    ? (raw.volume.current / raw.volume.sma20).toFixed(2)
    : 'N/A';

  return `## ${timeframe} Timeframe
Current BTC price: $${currentPrice}

Last ${recent.length} candles (chronological, most recent last):
Open:   ${fmtArray(opens)}
High:   ${fmtArray(highs)}
Low:    ${fmtArray(lows)}
Close:  ${fmtArray(closes)}
Volume: ${fmtArray(volumes)}

Computed Indicators:
- RSI(14): ${fmt(raw.rsi)}
- MACD Line: ${fmt(raw.macd?.line)}, Signal: ${fmt(raw.macd?.signal)}, Histogram: ${fmt(raw.macd?.histogram)}
- EMA20: ${fmt(raw.ema?.ema20)}, EMA50: ${fmt(raw.ema?.ema50)}, EMA200: ${fmt(raw.ema?.ema200)}
- Bollinger Upper: ${fmt(raw.bollinger?.upper)}, Middle: ${fmt(raw.bollinger?.middle)}, Lower: ${fmt(raw.bollinger?.lower)}
- Bollinger %B: ${fmt(raw.bollinger?.percentB)}
- ATR(14): ${fmt(raw.atr)}
- Volume vs 20-SMA: ${volumeRatio}x average

Technical Scores (Part 2 output):
- RSI Score: ${fmt(scores.rsi)}, MACD Score: ${fmt(scores.macd)}, EMA Score: ${fmt(scores.ema)}, BB Score: ${fmt(scores.bollinger)}
- Volume Modifier: ${scores.volumeModifier?.toFixed(1) ?? 'N/A'}x
- Combined Score: ${fmt(indicators?.combinedScore)} | Signal: ${indicators?.signal ?? 'N/A'}`;
}

const RESPONSE_FORMAT = `{
  "<timeframe>": {
    "direction": "bullish" | "bearish" | "neutral",
    "confidence": 0-100,
    "score": -1.0 to 1.0,
    "key_support": <number>,
    "key_resistance": <number>,
    "patterns_detected": ["pattern1", "pattern2"],
    "divergences": ["description if any"],
    "reasoning": "2-3 sentence summary of your analysis",
    "suggested_entry": <number or null>,
    "suggested_stop": <number or null>,
    "suggested_target": <number or null>
  }
}`;

/**
 * Build a batched prompt for multiple timeframes in one API call.
 *
 * @param {Array<{timeframe: string, candles: Array, indicators: Object}>} timeframeGroup
 * @returns {{ systemPrompt: string, userPrompt: string }}
 */
export function buildBatchPrompt(timeframeGroup) {
  const systemPrompt = `You are a quantitative BTC/USDT analyst. Analyze the following market data and respond ONLY with valid JSON. No markdown, no backticks, no explanation outside the JSON.

Analyze for:
1. Trend direction and strength
2. Key support and resistance levels
3. Chart patterns (double top/bottom, head and shoulders, triangles, flags, wedges)
4. Divergences between price and RSI/MACD
5. Key levels being tested
6. Volume confirmation or divergence`;

  const dataBlocks = timeframeGroup
    .map(({ timeframe, candles, indicators }) =>
      buildAnalysisPrompt(timeframe, candles, indicators)
    )
    .join('\n\n---\n\n');

  const tfKeys = timeframeGroup.map(g => `"${g.timeframe}"`).join(', ');

  const userPrompt = `${dataBlocks}

---

Respond with a JSON object keyed by timeframe (${tfKeys}). Use this exact structure per timeframe:
${RESPONSE_FORMAT}`;

  return { systemPrompt, userPrompt };
}
