/**
 * Crypto market monitor via CoinGecko public API (no key required for basic use)
 */

const COINGECKO_API = 'https://api.coingecko.com/api/v3';

// Cache to detect price movements between runs
const priceCache = new Map();

/**
 * Fetch current prices and 24h stats for the given coin IDs.
 * @param {string[]} coinIds  e.g. ['bitcoin', 'ethereum', 'solana']
 * @returns {Promise<Array>}
 */
export async function getCoinPrices(coinIds) {
  const ids = coinIds.join(',');
  const url =
    `${COINGECKO_API}/coins/markets` +
    `?vs_currency=usd` +
    `&ids=${encodeURIComponent(ids)}` +
    `&order=market_cap_desc` +
    `&sparkline=false` +
    `&price_change_percentage=1h,24h`;

  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`CoinGecko API error: ${res.status} ${res.statusText}`);
  }

  const coins = await res.json();

  return coins.map((c) => ({
    id: c.id,
    symbol: c.symbol.toUpperCase(),
    name: c.name,
    priceUsd: c.current_price,
    change1h: c.price_change_percentage_1h_in_currency ?? null,
    change24h: c.price_change_percentage_24h_in_currency ?? null,
    volume24h: c.total_volume,
    marketCap: c.market_cap,
    high24h: c.high_24h,
    low24h: c.low_24h,
    ath: c.ath,
    athChangePercent: c.ath_change_percentage,
  }));
}

/**
 * Compare current prices against the cache and return coins that have moved
 * significantly (above the threshold).
 * @param {Array}  coins
 * @param {number} thresholdPct  Minimum % change since last check to flag
 * @returns {Array} movers with added `sinceLastCheckPct` field
 */
export function detectMovers(coins, thresholdPct = 3) {
  const movers = [];

  for (const coin of coins) {
    const prev = priceCache.get(coin.id);
    if (prev !== undefined) {
      const pct = ((coin.priceUsd - prev) / prev) * 100;
      if (Math.abs(pct) >= thresholdPct) {
        movers.push({ ...coin, sinceLastCheckPct: pct });
      }
    }
    // Update cache
    priceCache.set(coin.id, coin.priceUsd);
  }

  return movers;
}

/**
 * Seed the price cache on first run (no movers emitted yet).
 * @param {Array} coins
 */
export function seedCache(coins) {
  for (const coin of coins) {
    priceCache.set(coin.id, coin.priceUsd);
  }
}
