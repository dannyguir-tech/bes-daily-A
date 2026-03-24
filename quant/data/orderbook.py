"""
data/orderbook.py — Fetches order book data and computes bid/ask imbalance.

Order Book Imbalance (OBI) = (bid_vol - ask_vol) / (bid_vol + ask_vol)
  +1.0 = all bids (strong buy pressure)
  -1.0 = all asks (strong sell pressure)
   0.0 = balanced
"""

import logging
import requests

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg

logger = logging.getLogger(__name__)


def _get(url: str, params: dict = None) -> dict | None:
    try:
        resp = requests.get(url, params=params, timeout=8)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("Orderbook fetch failed: %s", exc)
        return None


def fetch_binance_orderbook(symbol: str, depth: int = 20) -> dict | None:
    """
    Fetch top-N bid/ask levels from Binance spot.
    Returns raw {'bids': [[price, qty], ...], 'asks': [[price, qty], ...]} or None.
    """
    url = f"{cfg.BINANCE_BASE}/api/v3/depth"
    return _get(url, {'symbol': symbol, 'limit': depth})


def compute_obi(orderbook: dict, levels: int = 10) -> float:
    """
    Compute Order Book Imbalance from a raw orderbook dict.

    Parameters
    ----------
    orderbook : dict with 'bids' and 'asks' lists of [price_str, qty_str]
    levels    : how many price levels to sum on each side

    Returns
    -------
    float in [-1, 1]; returns 0.0 on error.
    """
    if not orderbook:
        return 0.0
    try:
        bid_vol = sum(float(q) for _, q in orderbook['bids'][:levels])
        ask_vol = sum(float(q) for _, q in orderbook['asks'][:levels])
        total = bid_vol + ask_vol
        if total == 0:
            return 0.0
        return (bid_vol - ask_vol) / total
    except (KeyError, TypeError, ValueError) as exc:
        logger.debug("OBI computation error: %s", exc)
        return 0.0


def get_obi(symbol: str, levels: int = 10) -> float:
    """
    Convenience: fetch orderbook and return OBI in one call.
    Returns 0.0 if the exchange is unreachable.
    """
    ob = fetch_binance_orderbook(symbol, depth=max(levels, 20))
    return compute_obi(ob, levels=levels)


def get_spread_pct(symbol: str) -> float:
    """
    Returns the bid-ask spread as a percentage of the mid price.
    Useful as a liquidity proxy. Returns 0.0 on error.
    """
    ob = fetch_binance_orderbook(symbol, depth=5)
    if not ob:
        return 0.0
    try:
        best_bid = float(ob['bids'][0][0])
        best_ask = float(ob['asks'][0][0])
        mid = (best_bid + best_ask) / 2
        return (best_ask - best_bid) / mid if mid > 0 else 0.0
    except (IndexError, ValueError):
        return 0.0
