"""feature_engine_v2.py — Extended features for multi-pair M5 forex model."""
import numpy as np
import pandas as pd


FEATURES_V2 = [
    "ret_1", "ret_2", "ret_3", "ret_5", "ret_10",
    "sma_ratio_5", "sma_ratio_10", "sma_ratio_20",
    "ema_ratio_5", "ema_ratio_10", "ema_ratio_20",
    "rsi", "atr", "bb_pos",
    "vol_10", "vol_30", "vol_ratio",
    "body_ratio", "upper_wick", "lower_wick",
    "hour_sin", "hour_cos",
    "eur_ret_1", "eur_ret_5", "eur_ret_15",
    "gbp_ret_1", "gbp_ret_5", "gbp_ret_15",
    "eur_jpy_corr_60", "gbp_jpy_corr_60",
    "eur_sma_ratio_20", "gbp_sma_ratio_20",
    "vwap_london_dist", "vwap_ny_dist",
    "above_london_vwap", "above_ny_vwap",
    "atr_percentile", "vol_of_vol",
]


def compute_base_features(df):
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


def add_cross_pair_features(df, eur, gbp):
    eur_ret = np.log(eur["Close"] / eur["Close"].shift(1))
    eur_ret5 = np.log(eur["Close"] / eur["Close"].shift(5))
    eur_ret15 = np.log(eur["Close"] / eur["Close"].shift(15))
    gbp_ret = np.log(gbp["Close"] / gbp["Close"].shift(1))
    gbp_ret5 = np.log(gbp["Close"] / gbp["Close"].shift(5))
    gbp_ret15 = np.log(gbp["Close"] / gbp["Close"].shift(15))

    df["eur_ret_1"] = eur_ret.reindex(df.index, method="ffill")
    df["eur_ret_5"] = eur_ret5.reindex(df.index, method="ffill")
    df["eur_ret_15"] = eur_ret15.reindex(df.index, method="ffill")
    df["gbp_ret_1"] = gbp_ret.reindex(df.index, method="ffill")
    df["gbp_ret_5"] = gbp_ret5.reindex(df.index, method="ffill")
    df["gbp_ret_15"] = gbp_ret15.reindex(df.index, method="ffill")

    jpy_ret = np.log(df["Close"] / df["Close"].shift(1))
    aligned_eur = eur_ret.reindex(df.index, method="ffill")
    aligned_gbp = gbp_ret.reindex(df.index, method="ffill")
    df["eur_jpy_corr_60"] = jpy_ret.rolling(60).corr(aligned_eur)
    df["gbp_jpy_corr_60"] = jpy_ret.rolling(60).corr(aligned_gbp)

    eur_sma20 = eur["Close"].rolling(20).mean()
    gbp_sma20 = gbp["Close"].rolling(20).mean()
    df["eur_sma_ratio_20"] = (eur["Close"] / eur_sma20 - 1).reindex(df.index, method="ffill")
    df["gbp_sma_ratio_20"] = (gbp["Close"] / gbp_sma20 - 1).reindex(df.index, method="ffill")
    return df


def add_session_vwap(df):
    df = df.copy()
    typical = (df["High"] + df["Low"] + df["Close"]) / 3
    vol = df["Volume"] if "Volume" in df.columns else pd.Series(1.0, index=df.index)

    for name, hour in [("london", 8), ("ny", 13)]:
        group = np.where(
            df.index.hour >= hour,
            df.index.normalize() + pd.to_timedelta(hour, unit="h"),
            df.index.normalize() - pd.Timedelta(days=1) + pd.to_timedelta(hour, unit="h"),
        )
        group = pd.Series(group, index=df.index)
        pv = typical * vol
        cum_pv = pv.groupby(group).cumsum()
        cum_v = vol.groupby(group).cumsum()
        vwap = cum_pv / cum_v
        df[f"vwap_{name}_dist"] = (df["Close"] / vwap - 1)
        df[f"above_{name}_vwap"] = (df["Close"] > vwap).astype(int)
    return df


def add_regime_features(df):
    df = df.copy()
    atr_series = df["atr"] if "atr" in df.columns else pd.Series(0.0, index=df.index)
    df["atr_percentile"] = atr_series.rolling(2000, min_periods=500).apply(
        lambda x: (x.iloc[-1] > x).mean() if len(x) else 0.5, raw=False
    )
    df["vol_of_vol"] = df["vol_10"].rolling(60).std()
    return df


def build_features_v2(df_jpy, df_eur, df_gbp):
    df = compute_base_features(df_jpy)
    df = add_cross_pair_features(df, df_eur, df_gbp)
    df = add_session_vwap(df)
    df = add_regime_features(df)
    return df
