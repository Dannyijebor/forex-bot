"""signal_engine_v5.py — 3-symbol × 2-direction primary+meta ensemble."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import numpy as np
import pandas as pd

from feature_engine_v2 import FEATURES_V2, build_features_v2

PIP_SIZES = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01}

# Primary prob must exceed this to fire
PRIMARY_THRESHOLD = 0.42

# Per-symbol, per-direction meta thresholds (loosened from backtest to allow more trades)
META_THRESHOLDS = {
    "EURUSD": {"up": 0.40, "down": 0.35},
    "GBPUSD": {"up": 0.45, "down": 0.45},
    "USDJPY": {"up": 0.40, "down": 0.45},
}

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
    df = pd.read_csv(path)
    date_col = df.columns[0]
    df[date_col] = pd.to_datetime(df[date_col]).dt.normalize()
    df = df.set_index(date_col)
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
    with open(d / "primary_up.json") as f: pu = json.load(f)
    with open(d / "primary_down.json") as f: pd_ = json.load(f)
    with open(d / "meta_up.json") as f: mu = json.load(f)
    with open(d / "meta_down.json") as f: md = json.load(f)
    with open(d / "features.json") as f: features = json.load(f)
    mean = np.load(d / "scaler_mean.npy").astype(np.float64)
    scale = np.load(d / "scaler_scale.npy").astype(np.float64)
    return {
        "primary_up": pu, "primary_down": pd_,
        "meta_up": mu, "meta_down": md,
        "features": features, "mean": mean, "scale": scale,
    }


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


def fetch_pair_live(client, account_id, symbol, count=1500):
    """Fetch M5 bars from TickerAll/MT5. Same source as execution."""
    try:
        candles = client.candles.get(
            account_id,
            symbol=TICKERALL_SYMBOLS[symbol],
            count=count,
            timeframe="M5",
        )
        if not candles:
            return None
        rows = []
        for c in candles:
            rows.append({
                "Date": pd.to_datetime(c.timestamp, unit="s", utc=True),
                "Open": float(c.open),
                "High": float(c.high),
                "Low": float(c.low),
                "Close": float(c.close),
                "Volume": float(getattr(c, "tick_volume", 0)),
            })
        df = pd.DataFrame(rows).set_index("Date").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        return df
    except Exception as e:
        print(f"  {symbol} live fetch failed: {type(e).__name__}: {e}")
        return None


def fetch_all_pairs_live(client, account_id, count=1500):
    """Fetch all 3 pairs from live MT5 broker."""
    return {
        sym: fetch_pair_live(client, account_id, sym, count)
        for sym in ["USDJPY", "EURUSD", "GBPUSD"]
    }


def fetch_all_pairs(days=7):
    return {sym: fetch_pair(sym, days) for sym in ["USDJPY", "EURUSD", "GBPUSD"]}


def score_symbol(symbol, primary_df, cross1_df, cross2_df, cross_daily):
    """Score one symbol → returns (buy_signal, sell_signal, details)."""
    try:
        models = load_symbol_models(f"models/{symbol.lower()}_v5")

        df = build_features_v2(primary_df, cross1_df, cross2_df)
        df = add_order_flow_features(df)

        df = df.reset_index()
        ts_col = df.columns[0]
        df["date"] = pd.to_datetime(df[ts_col]).dt.normalize().dt.tz_localize(None)
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

        # Primary predictions
        p_up = predict_hgb(models["primary_up"], x_scaled)
        p_down = predict_hgb(models["primary_down"], x_scaled)

        # Meta predictions (meta takes primary prob as extra feature)
        x_up = np.concatenate([x_scaled, [p_up]])
        x_down = np.concatenate([x_scaled, [p_down]])
        m_up = predict_hgb(models["meta_up"], x_up)
        m_down = predict_hgb(models["meta_down"], x_down)

        thr_up = META_THRESHOLDS[symbol]["up"]
        thr_down = META_THRESHOLDS[symbol]["down"]

        buy_ok = (p_up > PRIMARY_THRESHOLD) and (m_up > thr_up)
        sell_ok = (p_down > PRIMARY_THRESHOLD) and (m_down > thr_down)

        return {
            "symbol": symbol,
            "primary_up": float(p_up),
            "primary_down": float(p_down),
            "meta_up": float(m_up),
            "meta_down": float(m_down),
            "thr_up": thr_up,
            "thr_down": thr_down,
            "buy_qualifies": buy_ok,
            "sell_qualifies": sell_ok,
            "close": float(df["Close"].iloc[-1]),
            "timestamp": df.index[-1],
            "atr": float(df["atr"].iloc[-1]),
            "tickerall_symbol": TICKERALL_SYMBOLS[symbol],
            "pip_size": PIP_SIZES[symbol],
        }
    except Exception as e:
        print(f"  {symbol} scoring failed: {type(e).__name__}: {e}")
        return None


def score_all(pairs, cross_daily):
    results = []
    for symbol in ["EURUSD", "GBPUSD", "USDJPY"]:
        primary = pairs.get(symbol)
        if primary is None:
            continue
        others = [s for s in ["USDJPY", "EURUSD", "GBPUSD"] if s != symbol]
        cross1 = pairs.get(others[0])
        cross2 = pairs.get(others[1])
        if cross1 is None or cross2 is None:
            continue
        r = score_symbol(symbol, primary, cross1, cross2, cross_daily)
        if r:
            results.append(r)
    return results


def pick_best(results):
    """Return (symbol, side, confidence, result_dict) or None."""
    candidates = []
    for r in results:
        if r["buy_qualifies"]:
            candidates.append((r["symbol"], "BUY", r["meta_up"], r))
        if r["sell_qualifies"]:
            candidates.append((r["symbol"], "SELL", r["meta_down"], r))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[2])


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
        buy_mark = "✓" if r["buy_qualifies"] else "✗"
        sell_mark = "✓" if r["sell_qualifies"] else "✗"
        print(f"  {r['symbol']}: UP primary={r['primary_up']:.4f} meta={r['meta_up']:.4f} "
              f"(thr={r['thr_up']}) {buy_mark}  |  "
              f"DOWN primary={r['primary_down']:.4f} meta={r['meta_down']:.4f} "
              f"(thr={r['thr_down']}) {sell_mark}")

    best = pick_best(results)
    if best:
        sym, side, conf, _ = best
        print(f"\n  🎯 Best: {sym} {side} @ confidence {conf:.4f}")
    else:
        print("\n  No symbol qualifies.")
