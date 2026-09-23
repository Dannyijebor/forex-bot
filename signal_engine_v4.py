"""signal_engine_v4.py — 3-symbol primary+meta ensemble with cross-asset features."""
import json, joblib
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

from feature_engine_v2 import FEATURES_V2, build_features_v2

# Pip sizes per symbol
PIP_SIZES = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01}

# Meta thresholds per symbol (from Kaggle backtest)
META_THRESHOLDS = {"EURUSD": 0.40, "GBPUSD": 0.40, "USDJPY": 0.45}

# TickerAll/Exness symbol names
TICKERALL_SYMBOLS = {"EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm", "USDJPY": "USDJPYm"}


def add_order_flow_features(df):
    df = df.copy()
    rng = (df["High"] - df["Low"]).replace(0, np.nan)
    df["body_efficiency"] = (df["Close"] - df["Open"]).abs() / rng
    upper = df["High"] - df[["Open", "Close"]].max(axis=1)
    lower = df[["Open", "Close"]].min(axis=1) - df["Low"]
    df["wick_imbalance"] = (upper - lower) / rng
    if "Volume" in df.columns:
        vol_mean = df["Volume"].rolling(20).mean()
        df["volume_ratio_20"] = np.where(vol_mean > 0, df["Volume"]/vol_mean, np.nan)
        vol_clean = df["Volume"].replace(0, np.nan)
        df["vol_price_divergence"] = (
            np.log(df["Close"]/df["Close"].shift(5)) -
            np.log(vol_clean/vol_clean.shift(5))
        )
    else:
        df["volume_ratio_20"] = 1.0
        df["vol_price_divergence"] = 0.0
    df = df.replace([np.inf, -np.inf], np.nan)
    for c in ["body_efficiency","wick_imbalance","volume_ratio_20","vol_price_divergence"]:
        df[c] = df[c].clip(-1e6, 1e6)
    return df


def load_cross_assets(path="cross_assets_daily.csv"):
    """Load daily cross-asset features. Returns DataFrame indexed by date."""
    df = pd.read_csv(path)
    # First column is date
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()
    df = df.set_index(date_col)
    # Ensure index is naive datetime for merge with M5 dates
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
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


def load_symbol_models(symbol_dir):
    d = Path(symbol_dir)
    with open(d / "primary.json") as f:
        primary = json.load(f)
    with open(d / "meta.json") as f:
        meta = json.load(f)
    with open(d / "features.json") as f:
        features = json.load(f)
    mean = np.load(d / "scaler_mean.npy").astype(np.float64)
    scale = np.load(d / "scaler_scale.npy").astype(np.float64)
    return {
        "primary": primary, "meta": meta,
        "features": features,
        "mean": mean, "scale": scale,
    }


def fetch_pair(instrument_name, days=7):
    """Fetch M5 bars from Dukascopy."""
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
    return {sym: fetch_pair(sym, days) for sym in ["USDJPY", "EURUSD", "GBPUSD"]}


def score_symbol(symbol, primary_df, cross1_df, cross2_df, cross_daily):
    """Score one symbol: primary prob → meta prob."""
    try:
        models = load_symbol_models(f"models/{symbol.lower()}_v4")

        # Build V4 features
        df = build_features_v2(primary_df, cross1_df, cross2_df)
        df = add_order_flow_features(df)

        # Merge cross-assets by date
        df = df.reset_index()
        ts_col = df.columns[0]
        df["date"] = pd.to_datetime(df[ts_col]).dt.normalize().dt.tz_localize(None)

        # Build cross frame with explicit "date" column
        cross_copy = cross_daily.copy()
        cross_copy["date"] = pd.to_datetime(cross_copy.index).normalize()
        cross_copy = cross_copy.reset_index(drop=True)

        df = df.merge(cross_copy, on="date", how="left")
        df = df.set_index(ts_col).drop(columns=["date"], errors="ignore")

        features = models["features"]
        df = df.dropna(subset=features)
        if len(df) < 2:
            return None

        x = df[features].iloc[-1].to_numpy(dtype=np.float64)
        x_scaled = (x - models["mean"]) / models["scale"]

        # Primary prediction
        p_primary = predict_hgb(models["primary"], x_scaled)

        # Meta prediction (meta takes primary prob as additional feature)
        x_meta = np.concatenate([x_scaled, [p_primary]])
        p_meta = predict_hgb(models["meta"], x_meta)

        return {
            "symbol": symbol,
            "primary_prob": float(p_primary),
            "meta_prob": float(p_meta),
            "close": float(df["Close"].iloc[-1]),
            "timestamp": df.index[-1],
            "atr": float(df["atr"].iloc[-1]),
            "threshold": META_THRESHOLDS[symbol],
            "qualifies": p_primary > 0.5 and p_meta > META_THRESHOLDS[symbol],
            "tickerall_symbol": TICKERALL_SYMBOLS[symbol],
            "pip_size": PIP_SIZES[symbol],
        }
    except Exception as e:
        print(f"  {symbol} scoring failed: {type(e).__name__}: {e}")
        return None


def score_all(pairs, cross_daily):
    """Score all three symbols. Returns list of results."""
    results = []
    for symbol in ["EURUSD", "GBPUSD", "USDJPY"]:
        primary = pairs.get(symbol)
        if primary is None:
            continue
        # Cross pairs are the other two
        others = [s for s in ["USDJPY", "EURUSD", "GBPUSD"] if s != symbol]
        cross1 = pairs.get(others[0])
        cross2 = pairs.get(others[1])
        if cross1 is None or cross2 is None:
            continue
        r = score_symbol(symbol, primary, cross1, cross2, cross_daily)
        if r:
            results.append(r)
    return results


if __name__ == "__main__":
    print("Loading cross-assets...")
    cross_daily = load_cross_assets()
    print(f"  {len(cross_daily)} days, {len(cross_daily.columns)} features")

    print("Fetching 3 pairs...")
    pairs = fetch_all_pairs(days=7)
    for sym, df in pairs.items():
        if df is not None:
            print(f"  {sym}: {len(df):,} bars")

    print("\nScoring all symbols...")
    results = score_all(pairs, cross_daily)
    for r in results:
        mark = "✓" if r["qualifies"] else "✗"
        print(f"  {r['symbol']}: primary={r['primary_prob']:.4f}  "
              f"meta={r['meta_prob']:.4f}  (thr={r['threshold']}) {mark}")

    qualifies = [r for r in results if r["qualifies"]]
    if qualifies:
        best = max(qualifies, key=lambda r: r["meta_prob"])
        print(f"\n  Best qualified: {best['symbol']} @ meta={best['meta_prob']:.4f}")
    else:
        print("\n  No symbols qualify for trading.")
