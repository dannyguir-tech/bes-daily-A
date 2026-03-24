/**
 * AI analyzer using Claude to generate smart buy alerts
 */

import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic(); // reads ANTHROPIC_API_KEY from env

const MODEL = 'claude-opus-4-6';

/**
 * Analyze Polymarket buy activity and generate actionable alerts.
 * @param {Array} buys       Recent significant buy trades
 * @param {Array} markets    Top active markets for context
 * @returns {Promise<string>} Formatted alert text
 */
export async function analyzePolymarketBuys(buys, markets) {
  if (buys.length === 0) return null;

  const systemPrompt = `You are a prediction market intelligence analyst.
Your job is to analyze recent large buy activity on Polymarket and surface
actionable insights. Be concise, factual, and highlight what's notable.
Format output as clean text alerts, not markdown.`;

  const userPrompt = `Analyze these recent large BUY trades on Polymarket and identify notable patterns,
smart money moves, or anything worth alerting on.

RECENT LARGE BUYS (last 15 min):
${JSON.stringify(buys, null, 2)}

TOP ACTIVE MARKETS (by volume) for context:
${JSON.stringify(markets.slice(0, 10), null, 2)}

For each notable trade or pattern:
- State what happened (market, amount, price/probability)
- Explain why it's interesting
- Rate conviction level: HIGH / MEDIUM / LOW
- Suggest what to watch

Keep total response under 400 words. Only surface the most interesting signals.`;

  const message = await client.messages.create({
    model: MODEL,
    max_tokens: 600,
    messages: [{ role: 'user', content: userPrompt }],
    system: systemPrompt,
  });

  return message.content[0].text;
}

/**
 * Analyze crypto price movers and generate alerts.
 * @param {Array} movers     Coins with significant price movement
 * @param {Array} allCoins   All monitored coins for context
 * @returns {Promise<string>} Formatted alert text
 */
export async function analyzeCryptoMovers(movers, allCoins) {
  if (movers.length === 0) return null;

  const systemPrompt = `You are a crypto market analyst focused on identifying actionable
buy signals. Be brief, direct, and data-driven. No hype. Format as plain text alerts.`;

  const userPrompt = `These crypto assets just moved significantly. Analyze and generate buy alerts.

MOVERS (price change since last check):
${JSON.stringify(movers, null, 2)}

ALL MONITORED COINS (context):
${JSON.stringify(allCoins, null, 2)}

For each mover:
- State what moved and by how much
- Context: is this a continuation, reversal, breakout?
- Check 24h trend and volume for confirmation
- Buy signal strength: STRONG / MODERATE / WEAK / AVOID
- Key price levels to watch

Keep total response under 300 words. Focus on buy opportunities.`;

  const message = await client.messages.create({
    model: MODEL,
    max_tokens: 500,
    messages: [{ role: 'user', content: userPrompt }],
    system: systemPrompt,
  });

  return message.content[0].text;
}

/**
 * Generate a daily summary combining both markets.
 * @param {object} summary  { polyBuys, cryptoMovers, allCoins }
 * @returns {Promise<string>}
 */
export async function generateDailySummary({ polyBuys, cryptoMovers, allCoins }) {
  const systemPrompt = `You are a market intelligence assistant. Produce a concise daily
briefing covering crypto and prediction market signals. Plain text, no markdown.`;

  const userPrompt = `Generate a brief daily market buy-alert summary.

POLYMARKET NOTABLE BUYS TODAY:
${polyBuys.length > 0 ? JSON.stringify(polyBuys, null, 2) : 'No significant buys detected.'}

CRYPTO MOVERS TODAY:
${cryptoMovers.length > 0 ? JSON.stringify(cryptoMovers, null, 2) : 'No significant moves detected.'}

CRYPTO SNAPSHOT:
${JSON.stringify(allCoins, null, 2)}

Produce:
1. Top 3 signals of the day (cross-market)
2. One sentence on overall market sentiment
3. What to watch in the next session

Max 250 words.`;

  const message = await client.messages.create({
    model: MODEL,
    max_tokens: 400,
    messages: [{ role: 'user', content: userPrompt }],
    system: systemPrompt,
  });

  return message.content[0].text;
}
