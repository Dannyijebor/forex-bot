"""adaptive_engine.py — Self-evolving decision layer.

Four subsystems, all data-driven:
  1. Calibration: raw meta score -> empirical P(win) per symbol
  2. Bandit: UCB-style trust weight per (symbol, regime) arm
  3. Optimal thresholds: per-symbol threshold maximizing expected pips
  4. Signal meta-model: logistic regression on signal features

Every subsystem activates only after minimum sample sizes are met.
Zero data -> neutral weights -> identical to current behavior.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone

STATE_FILE = Path("adaptive_state.json")
LOG_FILE   = Path("signals_log.csv")
MODEL_FILE = Path("signal_meta_model.json")

# Minimum data thresholds before each subsystem "wakes up"
MIN_CALIBRATION_N = 20   # per symbol
MIN_BANDIT_ARM_N  = 15   # per (symbol, regime) arm
MIN_OPT_THR_N     = 30   # per symbol
MIN_META_MODEL_N  = 100  # total labeled signals


def load_labeled():
    """Return labeled signals df or None."""
    if not LOG_FILE.exists():
        return None
    try:
        df = pd.read_csv(LOG_FILE)
    except Exception:
        return None
    if "label" not in df.columns or "label_pnl_pips" not in df.columns:
        return None
    df = df[df["label"].isin(["win", "loss"])].copy()
    if len(df) == 0:
        return None
    df["label_pnl_pips"] = pd.to_numeric(df["label_pnl_pips"], errors="coerce")
    for c in ["meta_up", "meta_down", "primary_up", "primary_down", "boost", "penalty"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df["meta_max"] = df[["meta_up", "meta_down"]].max(axis=1)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"], utc=True)
    df["hour"] = df["ts_utc"].dt.hour
    df["win"] = (df["label"] == "win").astype(int)
    return df


def calibrate(df, symbol, n_buckets=5):
    """Empirical P(win) per meta_score bucket for one symbol."""
    s = df[df["symbol"] == symbol]
    if len(s) < MIN_CALIBRATION_N:
        return None
    try:
        s = s.copy()
        s["bucket"] = pd.qcut(s["meta_max"], q=n_buckets, labels=False, duplicates="drop")
    except Exception:
        return None
    out = []
    for b, g in s.groupby("bucket"):
        out.append({
            "lo": round(float(g["meta_max"].min()), 3),
            "hi": round(float(g["meta_max"].max()), 3),
            "n": int(len(g)),
            "win_rate": round(float(g["win"].mean()), 3),
            "avg_pips": round(float(g["label_pnl_pips"].mean()), 2),
        })
    return out


def bandit(df):
    """UCB-inspired trust weight per (symbol, regime)."""
    if len(df) < MIN_BANDIT_ARM_N * 3:
        return {}
    out = {}
    for (sym, reg), g in df.groupby(["symbol", "regime"]):
        n = len(g)
        if n < MIN_BANDIT_ARM_N:
            out["%s|%s" % (sym, reg)] = {"weight": 1.0, "n": n, "reason": "explore"}
            continue
        wr = float(g["win"].mean())
        avg_pips = float(g["label_pnl_pips"].mean())
        if avg_pips > 3:
            w = min(1.5, 1.0 + avg_pips / 50.0)
            reason = "positive_ev"
        elif avg_pips < -1:
            w = max(0.4, 1.0 + avg_pips / 50.0)
            reason = "negative_ev"
        else:
            w = 1.0
            reason = "neutral"
        out["%s|%s" % (sym, reg)] = {
            "weight": round(w, 3), "n": n, "win_rate": round(wr, 3),
            "avg_pips": round(avg_pips, 2), "reason": reason,
        }
    return out


def optimal_threshold(df, symbol):
    """Threshold that maximizes expected pips on this symbol's history."""
    s = df[df["symbol"] == symbol]
    if len(s) < MIN_OPT_THR_N:
        return None
    best_t, best_ev, best_n = None, -1e9, 0
    for t in np.arange(0.30, 0.80, 0.02):
        sel = s[s["meta_max"] >= t]
        if len(sel) < 8:
            continue
        ev = float(sel["label_pnl_pips"].mean())
        if ev > best_ev:
            best_t, best_ev, best_n = round(float(t), 2), round(ev, 2), len(sel)
    if best_t is None:
        return None
    return {"threshold": best_t, "ev_pips": best_ev, "n_passing": best_n}


def train_signal_meta_model(df):
    """Fit simple logistic regression on signal features.

    Predicts P(win) from [symbol_onehot, regime_onehot, hour, meta_max,
    primary_max, boost, penalty]. Saved as coefficients to JSON.
    """
    if len(df) < MIN_META_MODEL_N:
        return None

    feats = df.copy()
    feats["primary_max"] = feats[["primary_up", "primary_down"]].max(axis=1)
    feats["hour_sin"] = np.sin(2 * np.pi * feats["hour"] / 24)
    feats["hour_cos"] = np.cos(2 * np.pi * feats["hour"] / 24)

    # one-hot
    symbols = sorted(feats["symbol"].unique())
    regimes = sorted(feats["regime"].fillna("unknown").unique())
    for s in symbols[1:]:
        feats["sym_%s" % s] = (feats["symbol"] == s).astype(int)
    for r in regimes[1:]:
        feats["reg_%s" % r] = (feats["regime"] == r).astype(int)

    cols = ["meta_max", "primary_max", "boost", "penalty", "hour_sin", "hour_cos"]
    cols += ["sym_%s" % s for s in symbols[1:]]
    cols += ["reg_%s" % r for r in regimes[1:]]
    cols = [c for c in cols if c in feats.columns]

    X = feats[cols].fillna(0).values
    y = feats["win"].values

    # manual logistic via gradient descent (avoids sklearn dependency)
    n, d = X.shape
    w = np.zeros(d)
    b = 0.0
    lr = 0.1
    for _ in range(500):
        z = X @ w + b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad_w = (X.T @ (p - y)) / n + 0.01 * w
        grad_b = float((p - y).mean())
        w -= lr * grad_w
        b -= lr * grad_b

    return {
        "features": cols,
        "coefficients": [round(float(v), 5) for v in w],
        "intercept": round(float(b), 5),
        "n_train": int(n),
        "train_win_rate": round(float(y.mean()), 3),
        "symbols": symbols,
        "regimes": regimes,
    }


def update_state():
    df = load_labeled()
    state = {
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "n_labeled": 0 if df is None else int(len(df)),
        "calibration": {},
        "bandit": {},
        "optimal_thresholds": {},
        "meta_model_trained": False,
    }
    if df is None:
        STATE_FILE.write_text(json.dumps(state, indent=2))
        print("No labeled data yet. Wrote empty state.")
        return state

    for sym in sorted(df["symbol"].unique()):
        cal = calibrate(df, sym)
        if cal:
            state["calibration"][sym] = cal
        opt = optimal_threshold(df, sym)
        if opt:
            state["optimal_thresholds"][sym] = opt

    state["bandit"] = bandit(df)

    mm = train_signal_meta_model(df)
    if mm:
        MODEL_FILE.write_text(json.dumps(mm, indent=2))
        state["meta_model_trained"] = True

    STATE_FILE.write_text(json.dumps(state, indent=2))
    return state


if __name__ == "__main__":
    import sys
    st = update_state()
    print(json.dumps(st, indent=2))
