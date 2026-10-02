"""feature_engine_v3.py — v2 features + Fibonacci, swings, MTF, round numbers, strength.

Pure superset of v2. Same input signature, adds ~30 new features.
Existing v2 models ignore unknown columns; new models (trained via retrain_models.py)
will pick these up automatically.
"""

import numpy as np
import pandas as pd

from feature_engine_v2 import build_features_v2


# ============================================================
# Fibonacci retracement confluence
# ============================================================
FIB_LEVELS = [0.236, 0.382, 0.5, 0.618, 0.786]

def add_fibonacci_features(df, lookback=100):
    """Distance to nearest recent-swing-derived Fib level + confluence count.

    Uses rolling max/min over `lookback` bars as a proxy for the current
    swing high/low. Standard approach when you don't have swing-detection.
    """
    hi = df["High"].rolling(lookback, min_periods=20).max()
    lo = df["Low"].rolling(lookback, min_periods=20).min()
    rng = (hi - lo).replace(0, np.nan)
    close = df["Close"]

    # Where in the range is the close? [0, 1]
    pos = ((close - lo) / rng).clip(0, 1)
    df["fib_range_pos"] = pos

    # Distance (in range-units) to nearest Fib level
    dists = [np.abs(pos - lvl) for lvl in FIB_LEVELS]
    df["fib_min_dist"] = pd.concat(dists, axis=1).min(axis=1)
    df["fib_at_level"] = (df["fib_min_dist"] < 0.02).astype(int)

    # Confluence: how many Fib levels are within 5% of range
    df["fib_confluence"] = sum((np.abs(pos - lvl) < 0.05).astype(int) for lvl in FIB_LEVELS)

    # Distance in price to nearest Fib level
    fib_prices = [lo + lvl * rng for lvl in FIB_LEVELS]
    dist_price = [np.abs(close - fp) for fp in fib_prices]
    df["fib_price_dist"] = pd.concat(dist_price, axis=1).min(axis=1) / close

    return df


# ============================================================
# Swing detection + structure
# ============================================================
def add_swing_features(df, window=20):
    """Local swing highs/lows, structure breaks, bars since last swing."""
    roll_max = df["High"].rolling(window, min_periods=5).max()
    roll_min = df["Low"].rolling(window, min_periods=5).min()

    # Is current bar at a rolling extreme?
    df["is_swing_high"] = (df["High"] >= roll_max).astype(int)
    df["is_swing_low"] = (df["Low"] <= roll_min).astype(int)

    # Bars since last swing high / low
    sh_idx = df["is_swing_high"].replace(0, np.nan).ffill().notna()
    sl_idx = df["is_swing_low"].replace(0, np.nan).ffill().notna()
    df["bars_since_swing_high"] = df["is_swing_high"].cumsum().pipe(
        lambda x: x - x.where(df["is_swing_high"].astype(bool)).ffill()
    ).fillna(window * 2).clip(upper=window * 2)
    df["bars_since_swing_low"] = df["is_swing_low"].cumsum().pipe(
        lambda x: x - x.where(df["is_swing_low"].astype(bool)).ffill()
    ).fillna(window * 2).clip(upper=window * 2)

    # Distance to recent swing (in ATR units)
    if "atr" in df.columns:
        atr = df["atr"].replace(0, np.nan)
        df["dist_to_swing_high_atr"] = (roll_max - df["Close"]) / atr
        df["dist_to_swing_low_atr"] = (df["Close"] - roll_min) / atr
    else:
        df["dist_to_swing_high_atr"] = (roll_max - df["Close"]) / df["Close"]
        df["dist_to_swing_low_atr"] = (df["Close"] - roll_min) / df["Close"]

    return df


# ============================================================
# Multi-timeframe trend (H1/H4 proxy from M5)
# ============================================================
def add_mtf_trend(df):
    """Aggregate M5 -> H1 (12 bars), H4 (48 bars) trend slope + RSI.

    Uses rolling averages instead of resampling, so it stays aligned
    with M5 index and has no gaps.
    """
    close = df["Close"]
    for period, name in [(12, "h1"), (48, "h4")]:
        ma = close.rolling(period, min_periods=period // 2).mean()
        df["%s_ma" % name] = ma
        # Slope as % change over the window
        df["%s_slope" % name] = (ma - ma.shift(period // 2)) / ma.replace(0, np.nan)
        # Price vs MA
        df["%s_dist" % name] = (close - ma) / ma.replace(0, np.nan)
        # Agreement: is M5 above H1 above H4?
    df["mtf_align_bull"] = (
        (close > df["h1_ma"]).astype(int)
        + (df["h1_ma"] > df["h4_ma"]).astype(int)
    )
    df["mtf_align_bear"] = (
        (close < df["h1_ma"]).astype(int)
        + (df["h1_ma"] < df["h4_ma"]).astype(int)
    )
    return df


# ============================================================
# Round-number proximity (psychological levels)
# ============================================================
def add_round_number_features(df):
    """Distance to nearest round price level, normalized by price."""
    close = df["Close"]

    # Detect the pip-size of the symbol from data (rough heuristic):
    # if price > 50 (JPY pairs), levels every 0.50; else every 0.0050
    is_jpy = close.mean() > 50
    if is_jpy:
        levels = [0.5, 1.0, 5.0]
        grid = 0.5
    else:
        levels = [0.005, 0.01, 0.05]
        grid = 0.005

    nearest = (close / grid).round() * grid
    df["dist_to_round"] = np.abs(close - nearest) / close
    df["at_round_50"] = (np.abs(close - (close / grid).round() * grid) / close < 0.0002).astype(int)

    # Bigger levels
    big_grid = 1.0 if is_jpy else 0.01
    nearest_big = (close / big_grid).round() * big_grid
    df["dist_to_biground"] = np.abs(close - nearest_big) / close
    df["at_biground"] = (df["dist_to_biground"] < 0.0002).astype(int)

    return df


# ============================================================
# Currency strength index (relative)
# ============================================================
def add_strength_index(df, df_eur, df_gbp):
    """Relative strength of the base currency vs the other two majors.

    For a given pair, compute short-window return of this pair vs cross pairs.
    Positive value = this pair's base currency is stronger than average.
    """
    # 12-bar (1h) return of each pair
    def ret12(x):
        try:
            return (x["Close"] / x["Close"].shift(12)) - 1
        except Exception:
            return pd.Series(index=df.index, dtype=float)

    try:
        r_self = ret12(df).reset_index(drop=True)
        r_eur = ret12(df_eur).reset_index(drop=True)
        r_gbp = ret12(df_gbp).reset_index(drop=True)
        # Pad to same length
        n = len(df)
        if len(r_eur) < n:
            r_eur = r_eur.reindex(range(n)).ffill()
        if len(r_gbp) < n:
            r_gbp = r_gbp.reindex(range(n)).ffill()
        avg = (r_eur + r_gbp) / 2
        df["strength_vs_peers"] = r_self.values - avg.values
    except Exception:
        df["strength_vs_peers"] = 0.0

    return df


# ============================================================
# Main entry point
# ============================================================
def build_features_v3(df_jpy, df_eur, df_gbp):
    """v2 features + v3 expansion. Returns DataFrame with all feature columns."""
    df = build_features_v2(df_jpy, df_eur, df_gbp)

    # Add v3 layers (order matters — some depend on earlier ones)
    try:
        df = add_fibonacci_features(df)
    except Exception:
        pass
    try:
        df = add_swing_features(df)
    except Exception:
        pass
    try:
        df = add_mtf_trend(df)
    except Exception:
        pass
    try:
        df = add_round_number_features(df)
    except Exception:
        pass
    try:
        df = add_strength_index(df, df_eur, df_gbp)
    except Exception:
        pass

    return df
