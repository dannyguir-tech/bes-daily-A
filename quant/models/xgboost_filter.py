"""
models/xgboost_filter.py — XGBoost binary classifier to filter signals.

Input  : feature vector from FeatureSet.to_ml_vector()
Output : probability of trade success [0, 1]

Training labels: 1 if forward return over ML_FORWARD_PERIODS > ATR, else 0.
Training data  : bootstrap from 90 days of hourly candles on first run,
                 retrain every RETRAIN_INTERVAL_H hours.

Model is saved/loaded from ML_MODEL_DIR per symbol.
"""

from __future__ import annotations

import os
import time
import logging
import numpy as np
import pandas as pd

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config as cfg

logger = logging.getLogger(__name__)

# Lazy imports — only needed at runtime, not import time
_xgb = None
_joblib = None


def _imports():
    global _xgb, _joblib
    if _xgb is None:
        import xgboost as xgb
        import joblib
        _xgb = xgb
        _joblib = joblib


def _model_path(symbol: str) -> str:
    os.makedirs(cfg.ML_MODEL_DIR, exist_ok=True)
    return os.path.join(cfg.ML_MODEL_DIR, f'xgb_{symbol}.pkl')


def _meta_path(symbol: str) -> str:
    return os.path.join(cfg.ML_MODEL_DIR, f'xgb_{symbol}_meta.json')


# ─── Feature/label construction ──────────────────────────────────────────────

def _make_features_labels(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """
    Build feature matrix X and binary labels y from a historical OHLCV DataFrame
    (with indicators already computed).

    Label = 1 if the forward return over ML_FORWARD_PERIODS candles exceeds ATR.
    """
    from features import indicators as ind
    df = ind.compute_all(df)
    df = df.dropna()

    if len(df) < cfg.ML_FORWARD_PERIODS + 20:
        return np.array([]), np.array([])

    # Forward return label
    fwd_return = df['close'].shift(-cfg.ML_FORWARD_PERIODS) / df['close'] - 1
    atr_pct    = df['atr'] / df['close']
    y = (fwd_return > atr_pct).astype(int)

    # Feature engineering (simplified — uses indicator columns)
    htf_enc = np.zeros(len(df))   # no HTF available in flat bootstrap data

    X_df = pd.DataFrame({
        'vwap_dist':      (df['close'] - df.get('vwap', df['close'])) / df.get('vwap', df['close']),
        'ewma_diff':      df.get('ewma_diff', 0),
        'atr_pct':        atr_pct,
        'roc':            df.get('roc', 0),
        'rsi_norm':       df.get('rsi', 50) / 100,
        'bb_pct':         df.get('bb_pct', 0.5),
        'oi_change_pct':  0.0,         # not available in candle history
        'ob_imbalance':   0.0,
        'funding_scaled': 0.0,
        'htf_enc':        htf_enc,
        'htf_roc':        0.0,
        'btc_corr':       0.5,
        'hh':             df.get('hh', False).astype(float),
        'll':             df.get('ll', False).astype(float),
    })

    # Drop last N rows (labels are NaN at the tail)
    valid = ~y.isna()
    X = X_df[valid].values
    y_arr = y[valid].values

    return X, y_arr


# ─── Training ─────────────────────────────────────────────────────────────────

def train(symbol: str, df: pd.DataFrame) -> bool:
    """
    Train and save an XGBoost classifier for a given symbol.

    Parameters
    ----------
    symbol : e.g. 'BTCUSDT'
    df     : long historical OHLCV DataFrame (1h or mixed)

    Returns
    -------
    True if training succeeded, False otherwise.
    """
    if not cfg.ML_ENABLED:
        return False
    _imports()

    logger.info("[XGB] Training model for %s on %d candles", symbol, len(df))
    X, y = _make_features_labels(df)

    if len(X) < 100:
        logger.warning("[XGB] Not enough data to train for %s (%d samples)", symbol, len(X))
        return False

    from sklearn.model_selection import train_test_split
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, shuffle=False)

    model = _xgb.XGBClassifier(
        n_estimators=200,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        use_label_encoder=False,
        eval_metric='logloss',
        verbosity=0,
        random_state=42,
    )
    model.fit(X_train, y_train,
              eval_set=[(X_val, y_val)],
              verbose=False)

    val_acc = (model.predict(X_val) == y_val).mean()
    logger.info("[XGB] %s val accuracy: %.3f", symbol, val_acc)

    _joblib.dump(model, _model_path(symbol))

    # Save metadata
    import json
    meta = {'trained_at': time.time(), 'val_accuracy': val_acc, 'n_samples': len(X)}
    with open(_meta_path(symbol), 'w') as f:
        json.dump(meta, f)

    return True


def _needs_retraining(symbol: str) -> bool:
    meta_path = _meta_path(symbol)
    if not os.path.exists(meta_path):
        return True
    import json
    try:
        with open(meta_path) as f:
            meta = json.load(f)
        age_hours = (time.time() - meta['trained_at']) / 3600
        return age_hours > cfg.RETRAIN_INTERVAL_H
    except Exception:
        return True


# ─── Inference ────────────────────────────────────────────────────────────────

_model_cache: dict[str, object] = {}


def predict(symbol: str, feature_vector: list[float]) -> float:
    """
    Return the probability of trade success for a given feature vector.

    Returns 0.5 if ML is disabled or model not available (neutral, no filter).
    Falls back to 0.5 so the system still generates alerts via rule-based logic.
    """
    if not cfg.ML_ENABLED:
        return 0.5

    _imports()
    path = _model_path(symbol)

    if symbol not in _model_cache:
        if not os.path.exists(path):
            logger.debug("[XGB] No model for %s — returning neutral 0.5", symbol)
            return 0.5
        try:
            _model_cache[symbol] = _joblib.load(path)
        except Exception as exc:
            logger.warning("[XGB] Failed to load model for %s: %s", symbol, exc)
            return 0.5

    model = _model_cache[symbol]
    X = np.array([feature_vector], dtype=float)
    try:
        prob = float(model.predict_proba(X)[0, 1])
        return prob
    except Exception as exc:
        logger.warning("[XGB] Inference error for %s: %s", symbol, exc)
        return 0.5


def maybe_retrain(symbol: str, df: pd.DataFrame) -> None:
    """Train/retrain the model if no saved model exists or weekly interval elapsed."""
    if _needs_retraining(symbol):
        # Invalidate cache so next predict() reloads the fresh model
        _model_cache.pop(symbol, None)
        train(symbol, df)
