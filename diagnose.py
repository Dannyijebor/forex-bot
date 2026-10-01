"""Self-diagnosis: find patterns in wins vs losses."""
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone


def diagnose():
    p = Path("signals_log.csv")
    if not p.exists():
        print("No signals_log.csv yet.")
        return

    df = pd.read_csv(p)

    if "label" not in df.columns or "label_pnl_pips" not in df.columns:
        print("signals_log.csv has no label columns yet.")
        print("This is normal for the first 15-20 minutes after deployment.")
        print("Wait until the bot has been running for at least 20 minutes.")
        return

    df = df[df["label"].isin(["win", "loss"])].copy()
    if len(df) < 10:
        print("Not enough labeled signals yet (%d). Need 10+." % len(df))
        print("Signals are labeled 15 minutes after they're recorded.")
        return

    df["label_pnl_pips"] = pd.to_numeric(df["label_pnl_pips"], errors="coerce")
    df["hour"] = pd.to_datetime(df["ts_utc"], utc=True).dt.hour

    print("=" * 60)
    print("SELF-DIAGNOSIS  --  %s" % datetime.now(timezone.utc).isoformat())
    print("=" * 60)
    print("Total labeled signals: %d" % len(df))
    print("Overall win rate: %.1f%%" % ((df["label"] == "win").mean() * 100))
    print("Avg pnl (pips):  %+.2f" % df["label_pnl_pips"].mean())

    findings = []

    print("\n--- By symbol ---")
    for sym in sorted(df["symbol"].unique()):
        s = df[df["symbol"] == sym]
        wr = (s["label"] == "win").mean() * 100
        n = len(s)
        print("  %-8s n=%3d  WR=%5.1f%%  avg pips=%+.2f" % (sym, n, wr, s["label_pnl_pips"].mean()))
        if n >= 10 and wr < 40:
            findings.append("LOW_EDGE_SYMBOL: %s WR=%.1f%% on n=%d" % (sym, wr, n))

    print("\n--- By regime ---")
    for reg in sorted(df["regime"].unique()):
        s = df[df["regime"] == reg]
        wr = (s["label"] == "win").mean() * 100
        n = len(s)
        print("  %-10s n=%3d  WR=%5.1f%%  avg pips=%+.2f" % (reg, n, wr, s["label_pnl_pips"].mean()))
        if n >= 10 and wr < 40:
            findings.append("LOW_EDGE_REGIME: %s WR=%.1f%% on n=%d" % (reg, wr, n))

    print("\n--- By hour (UTC) ---")
    by_h = df.groupby("hour").agg(
        n=("label", "count"),
        wr=("label", lambda x: (x == "win").mean() * 100),
        pips=("label_pnl_pips", "mean"))
    for h, row in by_h.iterrows():
        marker = ""
        if row["n"] >= 5 and row["wr"] < 30:
            marker = " <<<"
        if row["n"] >= 5 and row["wr"] > 70:
            marker = " ***"
        print("  %02d UTC  n=%3d  WR=%5.1f%%  avg=%+.2f%s" % (h, row["n"], row["wr"], row["pips"], marker))

    print("\n" + "=" * 60)
    print("FINDINGS")
    print("=" * 60)
    if not findings:
        print("  No clear patterns yet.")
    else:
        for f in findings:
            print("  * " + f)

    report = Path("diagnostics.txt")
    with open(report, "a") as f:
        f.write("\n[%s] %d signals, WR %.1f%%, findings: %s\n" % (
            datetime.now(timezone.utc).isoformat(), len(df),
            (df["label"] == "win").mean() * 100,
            "; ".join(findings) if findings else "none"))
    print("\nAppended to diagnostics.txt")


if __name__ == "__main__":
    diagnose()
