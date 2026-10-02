"""bars_cache.py — append-only rolling M5 bar cache for retraining.

Auto_trader calls cache_bars(pairs) every tick. Appends only the newest bar
per symbol (dedup by timestamp). Capped at MAX_ROWS so files don't grow forever.
"""

import pandas as pd
from pathlib import Path

MAX_ROWS = 200_000  # ~2 years of M5 bars per symbol


def cache_bars(pairs):
    """Append newest bar from each pair to per-symbol cache CSVs."""
    if not pairs:
        return
    for sym, df in pairs.items():
        if df is None or len(df) == 0:
            continue
        try:
            path = Path("bars_cache_%s.csv" % sym)
            latest = df.iloc[-1:].copy().reset_index()

            # Normalize first column to "Date"
            first_col = latest.columns[0]
            if first_col != "Date":
                latest = latest.rename(columns={first_col: "Date"})

            # Normalize OHLCV casing
            for c in list(latest.columns):
                if c.lower() in ("open", "high", "low", "close", "volume"):
                    latest = latest.rename(columns={c: c.capitalize()})

            if path.exists():
                old = pd.read_csv(path)
                combined = pd.concat([old, latest], ignore_index=True)
                combined = combined.drop_duplicates(subset=["Date"], keep="last")
                combined = combined.sort_values("Date").tail(MAX_ROWS)
            else:
                combined = latest

            combined.to_csv(path, index=False)
        except Exception:
            pass  # cache is best-effort; never crash the trading loop


def load_cache(symbol):
    """Load cached bars for one symbol, indexed by Date."""
    path = Path("bars_cache_%s.csv" % symbol)
    if not path.exists():
        return None
    try:
        df = pd.read_csv(path)
        if "Date" not in df.columns:
            return None
        df["Date"] = pd.to_datetime(df["Date"], utc=True)
        df = df.set_index("Date").sort_index()
        return df
    except Exception:
        return None
