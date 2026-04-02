/**
 * indicators/mockData.js — Generates synthetic BTC candles for testing
 * when no real exchange data is available.
 *
 * Uses a sine wave centered at $67,000 with noise to produce realistic
 * oscillating price patterns that generate meaningful indicator values.
 */

/**
 * Generate mock OHLCV candles with realistic BTC-like price movement.
 * @param {number} count  Number of candles to generate (default 200)
 * @returns {Array} Candle objects in DESC order (newest first) matching getCandles() format
 */
export function generateMockCandles(count = 200) {
  const candles = [];
  const baseTime = Date.now() - count * 5 * 60 * 1000;

  for (let i = 0; i < count; i++) {
    // Sine wave: 2 full cycles over 200 candles, centered at 67000
    const base = 67000 + 2000 * Math.sin((i * 2 * Math.PI) / 100);

    // Add random noise ±200
    const noise = (Math.random() - 0.5) * 400;
    const mid = base + noise;

    // Generate OHLCV from midpoint
    const range = 100 + Math.random() * 200;
    const open = mid + (Math.random() - 0.5) * range;
    const close = mid + (Math.random() - 0.5) * range;
    const high = Math.max(open, close) + Math.random() * 150;
    const low = Math.min(open, close) - Math.random() * 150;
    const volume = 50 + Math.random() * 200;

    candles.push({
      timestamp: baseTime + i * 5 * 60 * 1000,
      open: parseFloat(open.toFixed(2)),
      high: parseFloat(high.toFixed(2)),
      low: parseFloat(low.toFixed(2)),
      close: parseFloat(close.toFixed(2)),
      volume: parseFloat(volume.toFixed(4)),
    });
  }

  // Return DESC (newest first) to match getCandles() behavior
  return candles.reverse();
}
