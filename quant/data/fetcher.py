"""
data/fetcher.py — Fetches OHLCV, OI, funding rate data from Binance, Coinbase, Kraken.
All endpoints are public and require no API keys.
"""

import time
import logging
import requests
import pandas as pd
from datetime import datetime, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg

logger = logging.getLogger(__name__)

# Binance interval string map
_BINANCE_INTERVALS = {
    '1m': '1m', '5m': '5m', '15m': '15m', '1h': '1h',
    '4h': '4h', '1d': '1d', '1w': '1w', '1M': '1M',
}
# Coinbase granularity in seconds (None = unsupported)
_COINBASE_GRAN = {
    '1m': 60, '5m': 300, '15m': 900, '1h': 3600, '1d': 86400,
}
# Kraken interval in minutes (None = unsupported)
_KRAKEN_INTERVAL = {
    '1m': 1, '5m': 5, '15m': 15, '1h': 60,
    '4h': 240, '1d': 1440, '1w': 10080,
}


def _get(url: str, params: dict = None, retries: int = 3) -> dict | list | None:
    """HTTP GET with simple retry logic."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt == retries - 1:
                logger.warning("GET %s failed: %s", url, exc)
                return None
            time.sleep(1.5 ** attempt)
    return None


# ─── OHLCV ────────────────────────────────────────────────────────────────────

def fetch_binance_ohlcv(symbol: str, interval: str, limit: int = cfg.CANDLE_LIMIT) -> pd.DataFrame | None:
    """
    Fetch OHLCV candles from Binance spot API.
    Returns DataFrame with columns: [open, high, low, close, volume] indexed by UTC timestamp.
    """
    url = f"{cfg.BINANCE_BASE}/api/v3/klines"
    data = _get(url, {'symbol': symbol, 'interval': _BINANCE_INTERVALS[interval], 'limit': limit})
    if not data:
        return None
    df = pd.DataFrame(data, columns=[
        'ts', 'open', 'high', 'low', 'close', 'volume',
        'close_ts', 'quote_vol', 'trades', 'taker_buy_base', 'taker_buy_quote', '_'
    ])
    df['ts'] = pd.to_datetime(df['ts'], unit='ms', utc=True)
    df = df.set_index('ts')[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df


def fetch_coinbase_ohlcv(symbol: str, interval: str, limit: int = cfg.CANDLE_LIMIT) -> pd.DataFrame | None:
    """
    Fetch OHLCV from Coinbase Advanced Trade (public endpoint).
    Returns DataFrame with columns: [open, high, low, close, volume] indexed by UTC timestamp.
    """
    product = cfg.COINBASE_MAP.get(symbol)
    if not product:
        return None
    gran = _COINBASE_GRAN.get(interval)
    if gran is None:
        return None
    end_ts = int(time.time())
    start_ts = end_ts - gran * limit
    url = f"{cfg.COINBASE_BASE}/products/{product}/candles"
    data = _get(url, {'granularity': gran, 'start': start_ts, 'end': end_ts})
    if not data or not isinstance(data, list):
        return None
    # Coinbase returns [time, low, high, open, close, volume]
    df = pd.DataFrame(data, columns=['ts', 'low', 'high', 'open', 'close', 'volume'])
    df['ts'] = pd.to_datetime(df['ts'], unit='s', utc=True)
    df = df.set_index('ts').sort_index()[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df


def fetch_kraken_ohlcv(symbol: str, interval: str, limit: int = cfg.CANDLE_LIMIT) -> pd.DataFrame | None:
    """
    Fetch OHLCV from Kraken public API.
    Returns DataFrame with columns: [open, high, low, close, volume] indexed by UTC timestamp.
    """
    pair = cfg.KRAKEN_MAP.get(symbol)
    if not pair:
        return None
    kraken_interval = _KRAKEN_INTERVAL.get(interval)
    if kraken_interval is None:
        return None
    url = f"{cfg.KRAKEN_BASE}/0/public/OHLC"
    data = _get(url, {'pair': pair, 'interval': kraken_interval})
    if not data or data.get('error'):
        return None
    result = data.get('result', {})
    candles = result.get(pair) or result.get(list(result.keys())[0])
    if not candles:
        return None
    # Kraken returns [time, open, high, low, close, vwap, volume, count]
    df = pd.DataFrame(candles, columns=['ts', 'open', 'high', 'low', 'close', 'vwap', 'volume', 'count'])
    df['ts'] = pd.to_datetime(df['ts'].astype(int), unit='s', utc=True)
    df = df.set_index('ts')[['open', 'high', 'low', 'close', 'volume']].astype(float)
    return df.tail(limit)


def fetch_ohlcv_all_exchanges(symbol: str, interval: str) -> dict[str, pd.DataFrame]:
    """
    Fetch OHLCV from all three exchanges. Returns dict keyed by exchange name.
    Only includes exchanges that responded successfully.
    """
    results = {}
    for name, fn in [('binance', fetch_binance_ohlcv),
                     ('coinbase', fetch_coinbase_ohlcv),
                     ('kraken', fetch_kraken_ohlcv)]:
        df = fn(symbol, interval)
        if df is not None and len(df) > 20:
            results[name] = df
    return results


# ─── Open Interest ────────────────────────────────────────────────────────────

def fetch_open_interest(symbol: str) -> float | None:
    """
    Fetch current open interest from Binance futures (free public endpoint).
    Returns OI in USD notional, or None if unavailable.
    """
    url = f"{cfg.BINANCE_FUTURES}/fapi/v1/openInterest"
    data = _get(url, {'symbol': symbol})
    if not data:
        return None
    try:
        return float(data['openInterest'])
    except (KeyError, ValueError):
        return None


def fetch_oi_history(symbol: str, interval: str = '5m', limit: int = 50) -> pd.DataFrame | None:
    """
    Fetch historical OI from Binance futures.
    Returns DataFrame with [oi] indexed by UTC timestamp.
    """
    url = f"{cfg.BINANCE_FUTURES}/futures/data/openInterestHist"
    period_map = {'1m': '5m', '5m': '5m', '15m': '15m', '1h': '1h', '4h': '1h', '1d': '1h', '1w': '1h', '1M': '1h'}
    data = _get(url, {'symbol': symbol, 'period': period_map.get(interval, '5m'), 'limit': limit})
    if not data or not isinstance(data, list):
        return None
    df = pd.DataFrame(data)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df.set_index('timestamp')[['sumOpenInterest']].rename(
        columns={'sumOpenInterest': 'oi'}).astype(float)
    return df


# ─── Funding Rate ─────────────────────────────────────────────────────────────

def fetch_funding_rate(symbol: str) -> float | None:
    """
    Fetch the latest funding rate from Binance futures.
    Returns the rate as a decimal (e.g. 0.0001 = 0.01%), or None.
    """
    url = f"{cfg.BINANCE_FUTURES}/fapi/v1/fundingRate"
    data = _get(url, {'symbol': symbol, 'limit': 1})
    if not data or not isinstance(data, list) or not data:
        return None
    try:
        return float(data[-1]['fundingRate'])
    except (KeyError, ValueError):
        return None


# ─── Bootstrap historical data ────────────────────────────────────────────────

def fetch_bootstrap_ohlcv(symbol: str, days: int = cfg.BOOTSTRAP_DAYS) -> pd.DataFrame | None:
    """
    Fetch a long history of 1h candles from Binance for ML model training.
    Returns up to days×24 candles of hourly OHLCV.
    """
    limit = min(days * 24, 1000)
    return fetch_binance_ohlcv(symbol, '1h', limit=limit)
