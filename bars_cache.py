"""bars_cache.py — append-only rolling M5 bar cache for retraining."""

import pandas as pd
from pathlib import Path

MAX_ROWS = 200_000


def cache_bars(pairs):
    """Append newest bar from each pair to per-symbol cache CSVs."""
    if not pairs:
        return
    for sym, df in pairs.items():
        if df is None or len(df) == 0:
            continue
        try:
            path = Path("bars_cache_%s.csv" % sym)

            # Extract the newest bar and force the index column to be "Date"
            latest = df.iloc[-1:].reset_index()
            latest = latest.rename(columns={latest.columns[0]: "Date"})

            # Canonicalize OHLCV column names
            rename_map = {}
            for c in latest.columns:
                cl = str(c).lower()
                if cl == "open":   rename_map[c] = "Open"
                elif cl == "high": rename_map[c] = "High"
                elif cl == "low":  rename_map[c] = "Low"
                elif cl == "close":rename_map[c] = "Close"
                elif cl == "volume":rename_map[c] = "Volume"
            latest = latest.rename(columns=rename_map)

            # Keep only expected columns
            keep = ["Date", "Open", "High", "Low", "Close", "Volume"]
            latest = latest[[c for c in keep if c in latest.columns]]

            # Normalize Date to ISO string so both sides match for dedup
            latest["Date"] = pd.to_datetime(latest["Date"], utc=True).astype(str)

            if path.exists():
                old = pd.read_csv(path)
                if "Date" in old.columns:
                    old["Date"] = pd.to_datetime(old["Date"], utc=True).astype(str)
                combined = pd.concat([old, latest], ignore_index=True)
                combined = combined.drop_duplicates(subset=["Date"], keep="last")
                combined = combined.sort_values("Date").tail(MAX_ROWS)
            else:
                combined = latest

            combined.to_csv(path, index=False)
        except Exception as e:
            # Do NOT swallow silently — this is what was hiding the bug
            print("  cache_bars[%s] FAILED: %s: %s" % (sym, type(e).__name__, e))


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
