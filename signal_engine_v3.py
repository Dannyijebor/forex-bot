"""signal_engine_v3.py — Multi-symbol ensemble inference (HGB + RF + LGBM)."""
import json, joblib
from pathlib import Path
import numpy as np
import pandas as pd

from feature_engine_v2 import FEATURES_V2, build_features_v2
from signal_engine_v2 import fetch_all_pairs

FEATURES_V3 = FEATURES_V2 + ["body_efficiency", "wick_imbalance",
                             "volume_ratio_20", "vol_price_divergence"]


def add_order_flow_features(df):
    df = df.copy()
    rng = (df["High"] - df["Low"]).replace(0, np.nan)
    body = (df["Close"] - df["Open"]).abs()
    df["body_efficiency"] = body / rng
    upper = df["High"] - df[["Open","Close"]].max(axis=1)
    lower = df[["Open","Close"]].min(axis=1) - df["Low"]
    df["wick_imbalance"] = (upper - lower) / rng
    if "Volume" in df.columns:
        vol_mean = df["Volume"].rolling(20).mean()
        df["volume_ratio_20"] = np.where(vol_mean > 0, df["Volume"]/vol_mean, np.nan)
        vol_clean = df["Volume"].replace(0, np.nan)
        vol_ret = np.log(vol_clean / vol_clean.shift(5))
        close_ret = np.log(df["Close"] / df["Close"].shift(5))
        df["vol_price_divergence"] = close_ret - vol_ret
    else:
        df["volume_ratio_20"] = 1.0
        df["vol_price_divergence"] = 0.0
    df = df.replace([np.inf, -np.inf], np.nan)
    for c in ["body_efficiency","wick_imbalance","volume_ratio_20","vol_price_divergence"]:
        df[c] = df[c].clip(-1e6, 1e6)
    return df


def walk_tree_hgb(tree, x):
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


def predict_hgb(model_dict, x):
    raw = float(model_dict["baseline"])
    for stage in model_dict["trees"]:
        for tree in stage:
            raw += walk_tree_hgb(tree, x)
    return 1.0 / (1.0 + np.exp(-raw))


def walk_tree_rf(tree, x):
    idx = 0
    while tree["children_left"][idx] != -1:
        feat = tree["feature"][idx]
        thresh = tree["threshold"][idx]
        val = x[feat]
        if np.isnan(val):
            idx = tree["children_left"][idx]
        else:
            idx = tree["children_left"][idx] if val <= thresh else tree["children_right"][idx]
    return float(tree["value"][idx])


def predict_rf(model_dict, x):
    trees = model_dict["trees"]
    probs = [walk_tree_rf(t, x) for t in trees]
    return float(np.mean(probs))


def load_symbol_models(symbol_dir):
    d = Path(symbol_dir)
    with open(d / "model_hgb.json") as f:
        hgb = json.load(f)
    with open(d / "model_rf.json") as f:
        rf = json.load(f)
    try:
        lgbm = joblib.load(d / "model_lgbm.pkl")
    except Exception as e:
        print(f"  LGBM unavailable ({e}) — using HGB+RF only")
        lgbm = None
    mean = np.load(d / "scaler_mean.npy").astype(np.float64)
    scale = np.load(d / "scaler_scale.npy").astype(np.float64)
    with open(d / "features.json") as f:
        features = json.load(f)
    return {"hgb": hgb, "rf": rf, "lgbm": lgbm,
            "mean": mean, "scale": scale, "features": features}


def ensemble_predict(models, x_scaled):
    """Weighted ensemble: LGBM 0.4, HGB 0.35, RF 0.25."""
    p_hgb = predict_hgb(models["hgb"], x_scaled)
    p_rf = predict_rf(models["rf"], x_scaled)
    if models.get("lgbm") is not None:
        p_lgbm = float(models["lgbm"].predict_proba(x_scaled.reshape(1, -1))[0, 1])
        return 0.35 * p_hgb + 0.25 * p_rf + 0.40 * p_lgbm
    else:
        return 0.60 * p_hgb + 0.40 * p_rf


def percentile_threshold(symbol_dir, current_prob,
                         lookback=500, percentile=95, min_floor=0.40):
    """
    Rolling percentile threshold — fires on the top X% of recent probabilities.
    Adapts to whatever regime the market is currently in.

    Returns: (should_fire: bool, threshold_used: float)
    """
    from pathlib import Path
    import json as _json

    cache_file = Path(symbol_dir) / "recent_probs.json"

    recent = []
    if cache_file.exists():
        try:
            recent = _json.loads(cache_file.read_text())
        except Exception:
            recent = []

    # Compute threshold from PAST probabilities (not including current)
    if len(recent) >= 20:
        thresh = float(np.percentile(recent[-lookback:], percentile))
    else:
        thresh = 0.55   # warmup: need ~20 samples before percentile activates

    # Absolute floor — never fire on garbage even if it's "top 5%"
    thresh = max(thresh, min_floor)

    # Append current prob for next time
    recent.append(float(current_prob))
    recent = recent[-lookback:]
    try:
        cache_file.write_text(_json.dumps(recent))
    except Exception as e:
        print(f"  Warning: could not save recent_probs for {symbol_dir}: {e}")

    return current_prob >= thresh, thresh


def score_all_symbols(pairs_data, models_dir="models"):
    jpy, eur, gbp = pairs_data
    results = []
    for symbol, primary in [("EURUSD", eur), ("GBPUSD", gbp)]:
        try:
            models = load_symbol_models(f"{models_dir}/{symbol.lower()}")
            cross1 = jpy
            cross2 = gbp if symbol == "EURUSD" else eur
            df = build_features_v2(primary, cross1, cross2)
            df = add_order_flow_features(df)
            df = df.dropna(subset=FEATURES_V3)
            if len(df) < 2:
                continue
            x = df[FEATURES_V3].iloc[-1].to_numpy(dtype=np.float64)
            x_scaled = (x - models["mean"]) / models["scale"]
            prob = ensemble_predict(models, x_scaled)
            results.append({
                "symbol": symbol,
                "prob": prob,
                "close": float(df["Close"].iloc[-1]),
                "timestamp": df.index[-1],
            })
        except Exception as e:
            print(f"  {symbol} scoring failed: {e}")
            continue
    return results


if __name__ == "__main__":
    print("Fetching data...")
    pairs = fetch_all_pairs(days=7)
    if any(p is None for p in pairs):
        raise SystemExit("Data fetch failed")
    print("Scoring symbols...")
    results = score_all_symbols(pairs)
    for r in results:
        print(f"  {r['symbol']}: Prob={r['prob']:.4f}  Close={r['close']:.5f}  Bar={r['timestamp']}")
    if results:
        best = max(results, key=lambda r: r["prob"])
        print(f"\nBest: {best['symbol']} @ {best['prob']:.4f}")
