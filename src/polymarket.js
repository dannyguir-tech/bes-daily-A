/**
 * Polymarket API client
 * Uses the public Gamma API (no auth required)
 * Docs: https://docs.polymarket.com
 */

const GAMMA_API = 'https://gamma-api.polymarket.com';
const CLOB_API = 'https://clob.polymarket.com';

/**
 * Fetch recent BUY trades from Polymarket.
 * @param {number} lookbackMins - How many minutes back to look
 * @param {number} minSizeUsd  - Minimum trade size in USD to include
 * @returns {Promise<Array>} Array of flagged trade objects
 */
export async function getRecentBuys(lookbackMins = 15, minSizeUsd = 500) {
  const since = new Date(Date.now() - lookbackMins * 60 * 1000).toISOString();

  const url = new URL(`${GAMMA_API}/trades`);
  url.searchParams.set('taker_side', 'buy');
  url.searchParams.set('after', since);
  url.searchParams.set('limit', '200');

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`Polymarket Gamma API error: ${res.status} ${res.statusText}`);
  }

  const trades = await res.json();

  // Filter by minimum size and enrich
  const significant = trades
    .filter((t) => parseFloat(t.usdcSize ?? t.size ?? 0) >= minSizeUsd)
    .map((t) => ({
      id: t.id,
      market: t.market ?? t.conditionId,
      question: t.title ?? t.question ?? 'Unknown market',
      outcome: t.outcome ?? t.side,
      side: 'BUY',
      sizeUsd: parseFloat(t.usdcSize ?? t.size ?? 0),
      price: parseFloat(t.price ?? 0),
      timestamp: t.createdAt ?? t.timestamp,
      trader: t.maker ?? t.transactorAddress,
    }));

  return significant;
}

/**
 * Fetch the top active markets sorted by volume.
 * @param {number} limit
 * @returns {Promise<Array>}
 */
export async function getTopMarkets(limit = 20) {
  const url = new URL(`${GAMMA_API}/markets`);
  url.searchParams.set('active', 'true');
  url.searchParams.set('order', 'volumeNum');
  url.searchParams.set('ascending', 'false');
  url.searchParams.set('limit', String(limit));

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`Polymarket markets API error: ${res.status} ${res.statusText}`);
  }

  const markets = await res.json();

  return markets.map((m) => ({
    id: m.id ?? m.conditionId,
    question: m.question ?? m.title,
    volume24h: parseFloat(m.volume24hr ?? m.volume ?? 0),
    liquidity: parseFloat(m.liquidity ?? 0),
    outcomes: m.outcomes,
    outcomePrices: m.outcomePrices,
    endDate: m.endDate,
  }));
}

/**
 * Fetch last trade price for a specific market token.
 * @param {string} tokenId
 * @returns {Promise<number|null>}
 */
export async function getLastPrice(tokenId) {
  const res = await fetch(`${CLOB_API}/last-trade-price?token_id=${tokenId}`);
  if (!res.ok) return null;
  const data = await res.json();
  return parseFloat(data.price ?? 0);
}
