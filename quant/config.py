"""
config.py — Central configuration for the quantitative engine.
All thresholds, weights, and API settings live here.
Values are overridable via environment variables.
"""

import os
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))


# ─── Symbols ──────────────────────────────────────────────────────────────────
# Binance-style trading pairs (USDT quoted)
SYMBOLS: list[str] = os.getenv('QUANT_SYMBOLS', 'BTCUSDT,ETHUSDT,SOLUSDT,LINKUSDT,UNIUSDT').split(',')

# Map Binance symbol → Coinbase product id
COINBASE_MAP: dict[str, str] = {
    'BTCUSDT': 'BTC-USD',
    'ETHUSDT': 'ETH-USD',
    'SOLUSDT': 'SOL-USD',
    'LINKUSDT': 'LINK-USD',
    'UNIUSDT': 'UNI-USD',
}

# Map Binance symbol → Kraken pair
KRAKEN_MAP: dict[str, str] = {
    'BTCUSDT': 'XBTUSD',
    'ETHUSDT': 'ETHUSD',
    'SOLUSDT': 'SOLUSD',
    'LINKUSDT': 'LINKUSD',
    'UNIUSDT': 'UNIUSD',
}

# ─── Timeframes ───────────────────────────────────────────────────────────────
TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d', '1w', '1M']
PRIMARY_TF  = '5m'   # main signal timeframe
HTF         = '1h'   # higher timeframe for trend alignment (default for 5m)

# Timeframes that generate independent signals (excludes 1m — too noisy)
SIGNAL_TIMEFRAMES = ['5m', '15m', '1h', '4h', '1d', '1w', '1M']

# Higher timeframe mapping: each signal TF uses a higher TF for trend confirmation
HTF_MAP = {
    '5m':  '1h',
    '15m': '1h',
    '1h':  '4h',
    '4h':  '1d',
    '1d':  '1w',
    '1w':  '1M',
    '1M':  '1M',
}

# Per-timeframe cadence in seconds (how often each TF generates signals)
TF_INTERVALS = {
    '5m':  300,
    '15m': 900,
    '1h':  3600,
    '4h':  14400,
    '1d':  86400,
    '1w':  604800,
    '1M':  2592000,
}

# ─── Data fetching ────────────────────────────────────────────────────────────
CANDLE_LIMIT        = 200   # candles per fetch
BOOTSTRAP_DAYS      = int(os.getenv('ML_BOOTSTRAP_DAYS', '90'))
RETRAIN_INTERVAL_H  = 168   # retrain XGBoost every 7 days

# ─── Feature engineering ─────────────────────────────────────────────────────
EWMA_SHORT          = 9
EWMA_LONG           = 21
ATR_PERIOD          = 14
BB_PERIOD           = 20
BB_STD              = 2.0
ROC_PERIOD          = 10
CORR_PERIOD         = 30

# ─── Regime detection ─────────────────────────────────────────────────────────
ATR_VOL_THRESHOLD   = float(os.getenv('QUANT_ATR_VOL_THRESHOLD', '0.035'))  # atr/close
MOMENTUM_THRESHOLD  = 0.01    # min |ROC| to call it trending
EWMA_DIFF_THRESHOLD = 0.005   # min |ewma_short - ewma_long| / close

# ─── Signal generation ────────────────────────────────────────────────────────
TREND_OBI_MIN           = 0.10   # order book imbalance min for trend BUY
TREND_ROC_MIN           = 0.01   # min ROC for momentum breakout
MR_ROC_MAX              = 0.005  # max |ROC| for mean-reversion entry
MR_FUNDING_THRESHOLD    = -0.0005  # funding rate below this = contrarian BUY

# ─── Trade scoring ────────────────────────────────────────────────────────────
SCORE_THRESHOLD     = int(os.getenv('QUANT_SCORE_THRESHOLD', '70'))

# Dimension weights (must sum to 100)
SCORE_WEIGHTS = {
    'trend_alignment':    20,
    'vwap_alignment':     15,
    'order_book':         15,
    'oi_confirmation':    15,
    'momentum_quality':   15,
    'risk_reward':        20,
}

MIN_RISK_REWARD     = 2.0   # minimum R:R to score any points on that dimension

# ─── ML filter ───────────────────────────────────────────────────────────────
ML_PROB_THRESHOLD   = float(os.getenv('QUANT_ML_PROB_THRESHOLD', '0.6'))
ML_MODEL_DIR        = os.getenv('ML_MODEL_DIR', os.path.join(os.path.dirname(__file__), 'models', 'saved'))
ML_ENABLED          = os.getenv('ML_ENABLED', 'true').lower() == 'true'
ML_FORWARD_PERIODS  = 12    # forward candles used to label training data (12×5m = 1h)

# ─── Risk management ─────────────────────────────────────────────────────────
ATR_STOP_MULT       = float(os.getenv('QUANT_ATR_STOP_MULT', '1.75'))
ATR_TP_MULT         = float(os.getenv('QUANT_ATR_TP_MULT', '2.5'))
KELLY_FRACTION      = float(os.getenv('QUANT_KELLY_FRACTION', '0.25'))
MAX_RISK_PER_TRADE  = 0.01   # 1% of capital

# ─── Time-decay exit ─────────────────────────────────────────────────────────
MAX_HOLD_MINUTES    = int(os.getenv('QUANT_MAX_HOLD_MINUTES', '240'))
DECAY_PNL_THRESHOLD = 0.001  # exit if |pnl| < 0.1% after MAX_HOLD_MINUTES

# ─── Ensemble ─────────────────────────────────────────────────────────────────
ENSEMBLE_WEIGHTS = {
    'signal_strength': 0.30,
    'score':           0.35,
    'ml_prob':         0.35,
}

# ─── Output ───────────────────────────────────────────────────────────────────
ALERT_LOG_FILE      = os.getenv('QUANT_LOG_FILE', os.getenv('ALERT_LOG_FILE', 'alerts.log'))
SIGNAL_JSON_FILE    = os.path.join(os.path.dirname(__file__), 'signals', 'latest.json')
LIVE_INTERVAL_SECS  = int(os.getenv('QUANT_INTERVAL_SECS', '300'))   # 5 minutes

# ─── Database ────────────────────────────────────────────────────────────────
DB_PATH = os.getenv('DB_PATH', os.path.join(os.path.dirname(__file__), '..', 'data', 'signals.db'))

# ─── Binance endpoints ────────────────────────────────────────────────────────
BINANCE_BASE        = 'https://api.binance.com'
BINANCE_FUTURES     = 'https://fapi.binance.com'

# ─── Coinbase endpoint ────────────────────────────────────────────────────────
COINBASE_BASE       = 'https://api.exchange.coinbase.com'

# ─── Kraken endpoint ─────────────────────────────────────────────────────────
KRAKEN_BASE         = 'https://api.kraken.com'
