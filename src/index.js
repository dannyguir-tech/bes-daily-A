/**
 * BES Daily-A — AI-powered buy alerts for crypto + Polymarket
 *
 * Usage:
 *   cp .env.example .env   # add your ANTHROPIC_API_KEY
 *   npm install
 *   npm start
 */

import 'dotenv/config';
import cron from 'node-cron';

import { getRecentBuys, getTopMarkets } from './polymarket.js';
import { getCoinPrices, detectMovers, seedCache } from './crypto.js';
import { analyzePolymarketBuys, analyzeCryptoMovers, generateDailySummary } from './ai-analyzer.js';
import { emitAlert, info, error } from './alerts.js';

// ── Config ──────────────────────────────────────────────────────────────────
const CRON = process.env.CRON_SCHEDULE ?? '*/15 * * * *';
const POLY_MIN_BUY = parseFloat(process.env.POLY_MIN_BUY_SIZE ?? '500');
const POLY_LOOKBACK = parseInt(process.env.POLY_TRADE_LOOKBACK_MINS ?? '15', 10);
const CRYPTO_IDS = (process.env.CRYPTO_IDS ?? 'bitcoin,ethereum,solana,chainlink,uniswap').split(',');
const CRYPTO_THRESHOLD = parseFloat(process.env.CRYPTO_PRICE_CHANGE_THRESHOLD ?? '3');

// Track daily summary data
const dailyData = { polyBuys: [], cryptoMovers: [] };
let isFirstRun = true;

// ── Main check loop ──────────────────────────────────────────────────────────
async function runChecks() {
  info('Running market checks...');

  // ── Polymarket ─────────────────────────────────────────────────────────────
  try {
    const [buys, markets] = await Promise.all([
      getRecentBuys(POLY_LOOKBACK, POLY_MIN_BUY),
      getTopMarkets(20),
    ]);

    info(`Polymarket: ${buys.length} significant buy(s) found (>$${POLY_MIN_BUY})`);

    if (buys.length > 0) {
      dailyData.polyBuys.push(...buys);
      const analysis = await analyzePolymarketBuys(buys, markets);
      if (analysis) {
        emitAlert('POLYMARKET BUY ALERT', analysis);
      }
    }
  } catch (err) {
    error('Polymarket', err);
  }

  // ── Crypto ─────────────────────────────────────────────────────────────────
  try {
    const coins = await getCoinPrices(CRYPTO_IDS);

    if (isFirstRun) {
      seedCache(coins);
      info(`Crypto: seeded price cache for ${coins.length} coin(s). Movers will be detected next run.`);
    } else {
      const movers = detectMovers(coins, CRYPTO_THRESHOLD);
      info(`Crypto: ${movers.length} mover(s) detected (>${CRYPTO_THRESHOLD}% change since last check)`);

      if (movers.length > 0) {
        dailyData.cryptoMovers.push(...movers);
        const analysis = await analyzeCryptoMovers(movers, coins);
        if (analysis) {
          emitAlert('CRYPTO BUY ALERT', analysis);
        }
      }
    }
  } catch (err) {
    error('Crypto', err);
  }

  isFirstRun = false;
}

// ── Daily summary (runs at 11:55 PM) ─────────────────────────────────────────
async function runDailySummary() {
  info('Generating daily summary...');
  try {
    const allCoins = await getCoinPrices(CRYPTO_IDS);
    const summary = await generateDailySummary({
      polyBuys: dailyData.polyBuys,
      cryptoMovers: dailyData.cryptoMovers,
      allCoins,
    });
    emitAlert('DAILY MARKET SUMMARY', summary);
    // Reset daily accumulators
    dailyData.polyBuys = [];
    dailyData.cryptoMovers = [];
  } catch (err) {
    error('Daily summary', err);
  }
}

// ── Startup ───────────────────────────────────────────────────────────────────
async function main() {
  if (!process.env.ANTHROPIC_API_KEY) {
    process.stderr.write(
      'ERROR: ANTHROPIC_API_KEY is not set.\n' +
      'Copy .env.example to .env and add your key.\n'
    );
    process.exit(1);
  }

  info(`Starting BES Daily-A alert system`);
  info(`Polymarket: watching buys >$${POLY_MIN_BUY} over last ${POLY_LOOKBACK} min`);
  info(`Crypto: watching ${CRYPTO_IDS.join(', ')} — alerting on >${CRYPTO_THRESHOLD}% moves`);
  info(`Schedule: ${CRON}`);
  info('');

  // Run immediately on start, then on schedule
  await runChecks();

  cron.schedule(CRON, runChecks);
  cron.schedule('55 23 * * *', runDailySummary);

  info('Alert system running. Press Ctrl+C to stop.');
}

main().catch((err) => {
  process.stderr.write(`Fatal error: ${err.message}\n`);
  process.exit(1);
});
