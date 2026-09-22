"""signal_engine_v2.py — 38-feature inference for the multi-pair model."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

from feature_engine_v2 import FEATURES_V2, build_features_v2


def load_artifacts(models_dir="models"):
    d = Path(models_dir)
    with open(d / "model_trees.json") as f:
        model = json.load(f)
    mean = np.load(d / "scaler_mean.npy").astype(np.float64)
    scale = np.load(d / "scaler_scale.npy").astype(np.float64)
    with open(d / "features_m5.json") as f:
        features = json.load(f)
    return model, mean, scale, features


def walk_tree(tree, x):
    idx = 0
    while True:
        if tree["is_leaf"][idx]:
            return float(tree["value"][idx])
        feat = int(tree["feature_idx"][idx])
        thresh = float(tree["num_threshold"][idx])
        val = x[feat]
        if np.isnan(val):
            go_left = tree["missing_go_to_left"][idx] != 0
        else:
            go_left = val <= thresh
        idx = int(tree["left"][idx]) if go_left else int(tree["right"][idx])


def predict_proba(model, x_scaled):
    raw = float(model["baseline"])
    for stage in model["trees"]:
        for tree in stage:
            raw += walk_tree(tree, x_scaled)
    return 1.0 / (1.0 + np.exp(-raw))


def fetch_pair(instrument_name, days=7):
    import dukascopy_python as dp
    from dukascopy_python.instruments import (
        INSTRUMENT_FX_MAJORS_USD_JPY,
        INSTRUMENT_FX_MAJORS_EUR_USD,
        INSTRUMENT_FX_MAJORS_GBP_USD,
    )
    inst_map = {
        "USDJPY": INSTRUMENT_FX_MAJORS_USD_JPY,
        "EURUSD": INSTRUMENT_FX_MAJORS_EUR_USD,
        "GBPUSD": INSTRUMENT_FX_MAJORS_GBP_USD,
    }
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(days=days)
    df = dp.fetch(
        instrument=inst_map[instrument_name],
        interval=dp.INTERVAL_MIN_5,
        offer_side=dp.OFFER_SIDE_BID,
        start=start, end=end, max_retries=3,
    )
    if df is None or len(df) == 0:
        return None
    df = df.sort_index()
    df.columns = [c.capitalize() for c in df.columns]
    return df


def fetch_all_pairs(days=7):
    jpy = fetch_pair("USDJPY", days)
    eur = fetch_pair("EURUSD", days)
    gbp = fetch_pair("GBPUSD", days)
    return jpy, eur, gbp


def score_latest(models_dir="models", days=7, threshold=0.75):
    model, mean, scale, features = load_artifacts(models_dir)
    print(f"Model loaded: {model['n_iter']} iterations, {len(features)} features")

    jpy, eur, gbp = fetch_all_pairs(days=days)
    if jpy is None or eur is None or gbp is None:
        print("Data fetch failed for at least one pair")
        return None

    df = build_features_v2(jpy, eur, gbp)
    df = df.dropna(subset=features)
    if len(df) < 2:
        print("Insufficient bars after features")
        return None

    x = df[features].iloc[-1].to_numpy(dtype=np.float64)
    x_scaled = (x - mean) / scale
    prob = predict_proba(model, x_scaled)

    return {
        "timestamp": df.index[-1],
        "close": float(df["Close"].iloc[-1]),
        "prob_up": prob,
        "signal": "BUY" if prob >= threshold else "NONE",
    }


if __name__ == "__main__":
    result = score_latest()
    if result:
        print(f"\nLatest bar:  {result['timestamp']}")
        print(f"Close:       {result['close']:.3f}")
        print(f"Prob up:     {result['prob_up']:.4f}")
        print(f"Signal:      {result['signal']}")
