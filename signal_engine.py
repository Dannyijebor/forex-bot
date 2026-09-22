"""
signal_engine.py - Pure-numpy inference for the HistGradientBoosting model.
Loads model_trees.json + scaler arrays. No sklearn, no pickle.
"""
import json
from pathlib import Path
import numpy as np
import pandas as pd


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
    lr = float(model["learning_rate"])
    for stage in model["trees"]:
        for tree in stage:
            raw += walk_tree(tree, x_scaled)
    return 1.0 / (1.0 + np.exp(-raw))


def compute_features(df):
    df = df.copy()
    close, high, low, open_ = df["Close"], df["High"], df["Low"], df["Open"]
    df["ret_1"] = np.log(close / close.shift(1))
    for lag in (2, 3, 5, 10):
        df[f"ret_{lag}"] = np.log(close / close.shift(lag))
    for w in (5, 10, 20):
        df[f"sma_ratio_{w}"] = close / close.rolling(w).mean() - 1.0
        df[f"ema_ratio_{w}"] = close / close.ewm(span=w, adjust=False).mean() - 1.0
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(9).mean()
    loss = (-delta.clip(upper=0)).rolling(9).mean()
    df["rsi"] = 100 - (100 / (1 + gain / (loss + 1e-12)))
    tr = pd.concat([high - low, (high - close.shift(1)).abs(),
                    (low - close.shift(1)).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(10).mean() / close
    bb_mid = close.rolling(10).mean()
    bb_std = close.rolling(10).std()
    df["bb_pos"] = (close - bb_mid) / (2.0 * bb_std + 1e-12)
    df["vol_10"] = df["ret_1"].rolling(10).std()
    df["vol_30"] = df["ret_1"].rolling(30).std()
    df["vol_ratio"] = df["vol_10"] / (df["vol_30"] + 1e-12)
    rng = (high - low).replace(0, np.nan)
    df["body_ratio"] = (close - open_).abs() / rng
    df["upper_wick"] = (high - np.maximum(open_, close)) / rng
    df["lower_wick"] = (np.minimum(open_, close) - low) / rng
    hours = df.index.hour + df.index.minute / 60.0
    df["hour_sin"] = np.sin(2 * np.pi * hours / 24)
    df["hour_cos"] = np.cos(2 * np.pi * hours / 24)
    return df


def score_latest(models_dir="models", csv_path="USDJPY_5years_M5.csv", threshold=0.75):
    model, mean, scale, features = load_artifacts(models_dir)
    print(f"Loaded model: {model['n_iter']} iterations, {len(features)} features")
    df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
    df.columns = [c.capitalize() for c in df.columns]
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df = compute_features(df)
    df = df.dropna(subset=features)
    print(f"Scored on {len(df):,} bars")
    x = df[features].iloc[-1].to_numpy(dtype=np.float64)
    x_scaled = (x - mean) / scale
    prob = predict_proba(model, x_scaled)
    return {
        "timestamp": df.index[-1],
        "close": df["Close"].iloc[-1],
        "prob_up": prob,
        "signal": "BUY" if prob >= threshold else "NONE",
    }


if __name__ == "__main__":
    result = score_latest()
    print(f"\nLatest bar:  {result['timestamp']}")
    print(f"Close:       {result['close']:.3f}")
    print(f"Prob up:     {result['prob_up']:.4f}")
    print(f"Signal:      {result['signal']}")
