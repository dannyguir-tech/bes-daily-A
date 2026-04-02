/**
 * analysis/claude.js — Claude AI analysis module.
 *
 * Sends market data to the Anthropic API in batched calls and returns
 * structured JSON analysis per timeframe.
 */

import Anthropic from '@anthropic-ai/sdk';
import { buildBatchPrompt } from './prompt.js';
import { canMakeCall, recordCall, getRemainingCalls } from './rateLimiter.js';
import logger from '../logger.js';

const MODEL = process.env.CLAUDE_MODEL || 'claude-sonnet-4-20250514';

// Batch groups: 3 API calls instead of 7
const BATCH_GROUPS = [
  ['5m', '15m'],       // fast
  ['1h', '4h'],        // medium
  ['1d', '1w', '1M'],  // slow
];

const NEUTRAL_FALLBACK = {
  direction: 'neutral',
  confidence: 0,
  score: 0,
  key_support: null,
  key_resistance: null,
  patterns_detected: [],
  divergences: [],
  reasoning: 'Analysis unavailable',
  suggested_entry: null,
  suggested_stop: null,
  suggested_target: null,
};

// ─── JSON Parsing ───────────────────────────────────────────────────────────

/**
 * Parse JSON from Claude's response, handling various output formats.
 * Three-tier approach: direct parse → code fence extraction → brace extraction.
 */
function parseJSONResponse(text) {
  if (!text) return null;

  // Tier 1: Direct parse
  try {
    return JSON.parse(text);
  } catch { /* continue */ }

  // Tier 2: Extract from markdown code fence
  const fenceMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fenceMatch) {
    try {
      return JSON.parse(fenceMatch[1].trim());
    } catch { /* continue */ }
  }

  // Tier 3: Find first { to last } and parse
  const firstBrace = text.indexOf('{');
  const lastBrace = text.lastIndexOf('}');
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    try {
      return JSON.parse(text.slice(firstBrace, lastBrace + 1));
    } catch { /* continue */ }
  }

  return null;
}

// ─── Validation ─────────────────────────────────────────────────────────────

/**
 * Validate and normalize a single timeframe result.
 * Fills missing optional fields with defaults.
 */
function validateTfResult(result) {
  if (!result || typeof result !== 'object') return NEUTRAL_FALLBACK;

  const direction = typeof result.direction === 'string' ? result.direction : 'neutral';
  const confidence = typeof result.confidence === 'number'
    ? Math.max(0, Math.min(100, result.confidence))
    : 0;
  const score = typeof result.score === 'number'
    ? Math.max(-1, Math.min(1, result.score))
    : 0;
  const reasoning = typeof result.reasoning === 'string' && result.reasoning.length > 0
    ? result.reasoning
    : 'No reasoning provided';

  return {
    direction,
    confidence,
    score,
    key_support: typeof result.key_support === 'number' ? result.key_support : null,
    key_resistance: typeof result.key_resistance === 'number' ? result.key_resistance : null,
    patterns_detected: Array.isArray(result.patterns_detected) ? result.patterns_detected : [],
    divergences: Array.isArray(result.divergences) ? result.divergences : [],
    reasoning,
    suggested_entry: typeof result.suggested_entry === 'number' ? result.suggested_entry : null,
    suggested_stop: typeof result.suggested_stop === 'number' ? result.suggested_stop : null,
    suggested_target: typeof result.suggested_target === 'number' ? result.suggested_target : null,
  };
}

// ─── API Calls ──────────────────────────────────────────────────────────────

/**
 * Wait until the rate limiter allows a call.
 */
async function waitForRateLimit() {
  let waited = 0;
  while (!canMakeCall()) {
    if (waited > 30000) {
      throw new Error('Rate limit wait exceeded 30 seconds');
    }
    await new Promise(resolve => setTimeout(resolve, 1100));
    waited += 1100;
  }
}

/**
 * Make a single Claude API call with rate limiting.
 */
async function callClaude(client, systemPrompt, userPrompt) {
  await waitForRateLimit();
  recordCall();

  const message = await client.messages.create({
    model: MODEL,
    max_tokens: 1000,
    temperature: 0,
    system: systemPrompt,
    messages: [{ role: 'user', content: userPrompt }],
  });

  return message.content[0].text;
}

// ─── Exports ────────────────────────────────────────────────────────────────

/**
 * Analyze a single timeframe with Claude.
 *
 * @param {string} timeframe
 * @param {Array}  candles     From getCandles() (DESC order)
 * @param {Object} indicators  From analyzeTimeframe()
 * @returns {Object|null} Analysis result or null on failure
 */
export async function analyzeWithClaude(timeframe, candles, indicators) {
  if (!process.env.ANTHROPIC_API_KEY) {
    logger.warn('ANTHROPIC_API_KEY not set — cannot run Claude analysis');
    return null;
  }

  try {
    const client = new Anthropic();
    const { systemPrompt, userPrompt } = buildBatchPrompt([{ timeframe, candles, indicators }]);
    const rawText = await callClaude(client, systemPrompt, userPrompt);
    const parsed = parseJSONResponse(rawText);

    if (!parsed) {
      logger.warn(`${timeframe}: failed to parse Claude response`);
      logger.debug?.(`Raw response: ${rawText?.slice(0, 200)}`);
      return validateTfResult(null);
    }

    // Response might be keyed by timeframe or be a direct result
    const result = parsed[timeframe] || parsed;
    return validateTfResult(result);
  } catch (err) {
    logger.error(`Claude analysis failed for ${timeframe}: ${err.message}`);
    return null;
  }
}

/**
 * Analyze all timeframes with Claude in batched API calls.
 *
 * @param {Object} allCandles     { '5m': [...], '15m': [...], ... } from getCandles()
 * @param {Object} allIndicators  { '5m': {...}, '15m': {...}, ... } from analyzeAllTimeframes()
 * @returns {Object} Results keyed by timeframe
 */
export async function analyzeAllWithClaude(allCandles, allIndicators) {
  if (!process.env.ANTHROPIC_API_KEY) {
    logger.warn('ANTHROPIC_API_KEY not set — skipping Claude analysis');
    return {};
  }

  let client;
  try {
    client = new Anthropic();
  } catch (err) {
    logger.error(`Failed to initialize Anthropic client: ${err.message}`);
    return {};
  }

  const results = {};

  for (const group of BATCH_GROUPS) {
    // Build the group data
    const timeframeGroup = [];
    for (const tf of group) {
      if (allCandles[tf] && allIndicators[tf]) {
        timeframeGroup.push({
          timeframe: tf,
          candles: allCandles[tf],
          indicators: allIndicators[tf],
        });
      }
    }

    if (timeframeGroup.length === 0) continue;

    // Check rate limit
    if (getRemainingCalls() <= 0) {
      logger.warn('Rate limit reached — skipping remaining Claude analysis');
      break;
    }

    try {
      const { systemPrompt, userPrompt } = buildBatchPrompt(timeframeGroup);
      logger.info(`Analyzing ${group.join(', ')} with Claude...`);

      const rawText = await callClaude(client, systemPrompt, userPrompt);
      const parsed = parseJSONResponse(rawText);

      if (!parsed) {
        logger.warn(`Failed to parse Claude response for batch [${group.join(', ')}]`);
        for (const tf of group) {
          results[tf] = validateTfResult(null);
        }
        continue;
      }

      // Extract per-timeframe results
      for (const { timeframe } of timeframeGroup) {
        const tfResult = parsed[timeframe];
        results[timeframe] = validateTfResult(tfResult);
      }
    } catch (err) {
      logger.error(`Claude batch [${group.join(', ')}] failed: ${err.message}`);
      // Continue to next batch — partial results are OK
    }
  }

  return results;
}
