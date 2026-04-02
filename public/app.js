/**
 * app.js — Dashboard frontend logic.
 * Vanilla JS, no build step. Polls the API and renders signal cards.
 */

const POLL_INTERVAL = 30_000; // 30 seconds
const TF_LABELS = {
  all: 'All Signals',
  '5m': '5 Min Signals',
  '15m': '15 Min Signals',
  '1h': '1 Hour Signals',
  '4h': '4 Hour Signals',
  '1d': 'Daily Signals',
  '1w': 'Weekly Signals',
  '1M': 'Monthly Signals',
};

let activeTf = 'all';
let activeSymbol = '';

// ─── API ──────────────────────────────────────────────────────────────────────

async function fetchCounts() {
  try {
    const res = await fetch('/api/signals/counts');
    return await res.json();
  } catch {
    return {};
  }
}

async function fetchSignals(tf, symbol, limit = 50) {
  try {
    const params = new URLSearchParams({ limit: String(limit) });
    if (tf && tf !== 'all') params.set('timeframe', tf);
    if (symbol) params.set('symbol', symbol);
    const res = await fetch(`/api/signals?${params}`);
    const data = await res.json();
    return data.signals || [];
  } catch {
    return [];
  }
}

// ─── Rendering ────────────────────────────────────────────────────────────────

function formatPrice(p) {
  if (p >= 1000) return `$${p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  if (p >= 1) return `$${p.toFixed(4)}`;
  return `$${p.toFixed(6)}`;
}

function pctChange(from, to) {
  if (from === 0) return 'N/A';
  const pct = ((to - from) / from) * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function confidenceClass(conf) {
  if (conf >= 75) return 'fill--high';
  if (conf >= 50) return 'fill--mid';
  return 'fill--low';
}

function regimeClass(regime) {
  const r = (regime || '').toLowerCase();
  if (r === 'trending') return 'badge--trending';
  if (r === 'ranging') return 'badge--ranging';
  return 'badge--uncertain';
}

function formatTime(ts) {
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'UTC',
    }) + ' UTC';
  } catch {
    return ts;
  }
}

function renderSignalCard(signal) {
  const action = signal.action.toLowerCase();
  const actionClass = action === 'buy' ? 'action--buy' : 'action--sell';
  const cardClass = action === 'buy' ? 'signal--buy' : 'signal--sell';
  const conf = Math.round(signal.confidence || 0);
  const conditions = Array.isArray(signal.conditions_met) ? signal.conditions_met : [];
  const slPct = pctChange(signal.entry, signal.stop_loss);
  const tpPct = pctChange(signal.entry, signal.take_profit);
  const strategy = (signal.strategy || '').replace('_', ' ').toUpperCase();

  return `
    <div class="signal-card ${cardClass}">
      <div class="card-header">
        <span class="symbol">${signal.symbol}</span>
        <span class="action-badge ${actionClass}">${signal.action}</span>
        <span class="timeframe-badge">${signal.timeframe}</span>
      </div>

      <div class="confidence-bar">
        <span class="confidence-label">${conf}/100</span>
        <div class="confidence-fill ${confidenceClass(conf)}" style="width: ${conf}%"></div>
      </div>

      <div class="card-body">
        <div class="price-row">
          <div class="price-item">
            <span class="price-label">Entry</span>
            <span class="price-value">${formatPrice(signal.entry)}</span>
          </div>
          <div class="price-item">
            <span class="price-label">Stop Loss</span>
            <span class="price-value">${formatPrice(signal.stop_loss)}</span>
            <span class="price-pct">${slPct}</span>
          </div>
          <div class="price-item">
            <span class="price-label">Take Profit</span>
            <span class="price-value">${formatPrice(signal.take_profit)}</span>
            <span class="price-pct">${tpPct}</span>
          </div>
        </div>

        <div class="meta-row">
          <span class="badge ${regimeClass(signal.regime)}">${signal.regime}</span>
          <span class="badge">${strategy}</span>
          <span class="badge">Score: ${signal.score}</span>
          <span class="badge">ML: ${(signal.ml_prob || 0).toFixed(2)}</span>
        </div>

        ${conditions.length > 0 ? `
          <div class="conditions">
            ${conditions.map(c => `<span class="condition">${c}</span>`).join('')}
          </div>
        ` : ''}
      </div>

      <div class="card-footer">
        <time>${formatTime(signal.timestamp)}</time>
        <span>Kelly: ${(signal.kelly_fraction || 0).toFixed(3)}</span>
      </div>
    </div>
  `;
}

function renderSignals(signals) {
  const grid = document.getElementById('signal-grid');
  if (!signals || signals.length === 0) {
    grid.innerHTML = `
      <div class="empty-state">
        <p>No signals for this timeframe yet.</p>
        <code>python quant/main.py --mode live</code>
      </div>
    `;
    return;
  }
  grid.innerHTML = signals.map(renderSignalCard).join('');
}

function updateCounts(counts) {
  const tfs = ['all', '5m', '15m', '1h', '4h', '1d', '1w', '1M'];
  for (const tf of tfs) {
    const el = document.getElementById(`count-${tf}`);
    if (el) el.textContent = counts[tf] || 0;
  }
}

function updateLastUpdated() {
  const el = document.getElementById('last-updated');
  if (el) {
    const now = new Date();
    el.textContent = `Updated ${now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })}`;
  }
}

// ─── Refresh ──────────────────────────────────────────────────────────────────

async function refresh() {
  const [counts, signals] = await Promise.all([
    fetchCounts(),
    fetchSignals(activeTf, activeSymbol),
  ]);
  updateCounts(counts);
  renderSignals(signals);
  updateLastUpdated();
}

// ─── Event Handlers ───────────────────────────────────────────────────────────

function initEventHandlers() {
  // Timeframe buttons
  document.querySelectorAll('.tf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeTf = btn.dataset.tf;
      document.getElementById('active-tf-title').textContent = TF_LABELS[activeTf] || 'Signals';
      refresh();
    });
  });

  // Symbol filter
  document.getElementById('symbol-filter').addEventListener('change', (e) => {
    activeSymbol = e.target.value;
    refresh();
  });
}

// ─── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  initEventHandlers();
  refresh();
  setInterval(refresh, POLL_INTERVAL);
});
