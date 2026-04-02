/**
 * analysis/rateLimiter.js — In-memory rate limiter for Claude API calls.
 *
 * Enforces:
 * - Minimum 1 second between calls
 * - Maximum N calls per hour (configurable via CLAUDE_MAX_CALLS_PER_HOUR, default 20)
 */

const ONE_HOUR_MS = 60 * 60 * 1000;
const MIN_GAP_MS = 1000;

let callTimestamps = [];

function getMaxPerHour() {
  return parseInt(process.env.CLAUDE_MAX_CALLS_PER_HOUR || '20', 10);
}

function pruneOldEntries() {
  const cutoff = Date.now() - ONE_HOUR_MS;
  callTimestamps = callTimestamps.filter(ts => ts > cutoff);
}

/**
 * Check if we can make an API call right now.
 * @returns {boolean}
 */
export function canMakeCall() {
  pruneOldEntries();
  const maxPerHour = getMaxPerHour();

  if (callTimestamps.length >= maxPerHour) return false;

  if (callTimestamps.length > 0) {
    const lastCall = callTimestamps[callTimestamps.length - 1];
    if (Date.now() - lastCall < MIN_GAP_MS) return false;
  }

  return true;
}

/**
 * Record that an API call was just made.
 */
export function recordCall() {
  callTimestamps.push(Date.now());
}

/**
 * Get the number of remaining calls allowed this hour.
 * @returns {number}
 */
export function getRemainingCalls() {
  pruneOldEntries();
  return Math.max(0, getMaxPerHour() - callTimestamps.length);
}
