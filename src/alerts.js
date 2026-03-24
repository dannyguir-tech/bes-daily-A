/**
 * Alert output formatter — writes to console and/or log file
 */

import fs from 'fs';

const OUTPUT = process.env.ALERT_OUTPUT ?? 'console';
const LOG_FILE = process.env.ALERT_LOG_FILE ?? 'alerts.log';

function timestamp() {
  return new Date().toISOString();
}

function header(title) {
  const line = '='.repeat(60);
  return `\n${line}\n  ${title}\n  ${timestamp()}\n${line}`;
}

function divider() {
  return '-'.repeat(60);
}

/**
 * Emit an alert to console and/or file.
 * @param {string} section  Section label
 * @param {string} content  Alert body text
 */
export function emitAlert(section, content) {
  const text = `${header(section)}\n${content}\n`;
  if (OUTPUT === 'file') {
    fs.appendFileSync(LOG_FILE, text + '\n');
  } else {
    process.stdout.write(text + '\n');
  }
}

/**
 * Emit a structured summary of raw data before AI analysis (debug/info).
 * @param {string}  label
 * @param {Array}   items
 */
export function emitRawSummary(label, items) {
  if (items.length === 0) return;
  const lines = [`${divider()}`, `[RAW] ${label} — ${items.length} item(s):`];
  for (const item of items.slice(0, 5)) {
    lines.push(`  • ${JSON.stringify(item)}`);
  }
  if (items.length > 5) lines.push(`  … and ${items.length - 5} more`);
  emitAlert(label, lines.join('\n'));
}

/**
 * Emit a simple info/status line (no file write for these).
 * @param {string} msg
 */
export function info(msg) {
  process.stdout.write(`[${timestamp()}] ${msg}\n`);
}

/**
 * Emit an error.
 * @param {string} context
 * @param {Error}  err
 */
export function error(context, err) {
  process.stderr.write(`[${timestamp()}] ERROR [${context}]: ${err.message}\n`);
}
