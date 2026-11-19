p = "auto_trader.py"
s = open(p).read()

start_marker = "def label_signals("
end_marker = "    if updated:"
start_idx = s.find(start_marker)
end_idx = s.find(end_marker)

if start_idx == -1 or end_idx == -1:
    print("❌ Could not find function boundaries.")
    exit()

new_func = '''def label_signals(pairs, lookahead_min=240, pip_sizes=None):
    """For each unlabeled row in signals_log.csv, compute hypothetical outcome."""
    from pathlib import Path as _P
    if pip_sizes is None:
        pip_sizes = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01, "AUDUSD": 0.0001, "USDCAD": 0.0001, "NZDUSD": 0.0001, "EURGBP": 0.0001, "EURJPY": 0.01, "GBPJPY": 0.01}
    
    path = _P("signals_log.csv")
    if not path.exists():
        return
        
    df = pd.read_csv(path, low_memory=False)
    if "traded" not in df.columns:
        df["traded"] = ""
    df["traded"] = df["traded"].astype(object)
    
    if "skip_reason" not in df.columns:
        df["skip_reason"] = ""
    df["skip_reason"] = df["skip_reason"].astype(object)
    
    if "label" not in df.columns:
        df["label"] = ""
    df["label"] = df["label"].astype(object)
    
    if "label_pnl_pips" not in df.columns:
        df["label_pnl_pips"] = ""
    df["label_pnl_pips"] = df["label_pnl_pips"].astype(object)

    candidates = df[(df["buy_ok"] == "Y") | (df["sell_ok"] == "Y")].copy()
    candidates = candidates[candidates["label"].isna() | (candidates["label"] == "") | (candidates["label"] == "flat")]
    candidates = candidates.head(500)

    if len(candidates) == 0:
        return

    updated = 0
    now = datetime.now(timezone.utc)

    for idx, row in candidates.iterrows():
        sym = row["symbol"]
        try:
            ts = pd.to_datetime(row["ts_utc"], utc=True)
        except Exception:
            continue
        
        if (now - ts).total_seconds() / 60 < lookahead_min:
            continue
            
        bars = pairs.get(sym)
        if bars is None or len(bars) < 5:
            continue
            
        after = bars[bars.index >= ts]
        if len(after) < 2:
            continue
            
        entry = float(after["Close"].iloc[0])
        pip = pip_sizes.get(sym, 0.0001)
        
        # --- 1. DETERMINE SIDE FIRST ---
        side = None
        if row["buy_ok"] == "Y" and row["sell_ok"] != "Y":
            side = "BUY"
        elif row["sell_ok"] == "Y" and row["buy_ok"] != "Y":
            side = "SELL"
        elif row["buy_ok"] == "Y" and row["sell_ok"] == "Y":
            mu = float(row.get("meta_up", 0) or 0)
            md = float(row.get("meta_down", 0) or 0)
            side = "BUY" if mu >= md else "SELL"
            
        if side is None:
            df.at[idx, "label"] = "no_signal"
            updated += 1
            continue

        # --- 2. APPLY LIVE LOGIC ---
        side = apply_contrarian_logic(sym, side)
        
        champ_dna = COUNCIL_STATE["champion"]["dna"]
        if champ_dna.get("block_pair") == f"{sym}_{side}":
            df.at[idx, "label"] = "blocked_by_council"
            continue
        if champ_dna.get("block_hour") == ts.hour:
            df.at[idx, "label"] = "blocked_by_hour"
            continue
        if champ_dna.get("block_regime") == row.get("regime"):
            df.at[idx, "label"] = "blocked_by_regime"
            continue

        # --- 3. CALCULATE DYNAMIC SL/TP NOW THAT SIDE IS KNOWN ---
        tp_pips, sl_pips = get_dynamic_sl_tp(bars, side)

        window = after.iloc[1:48]
        tp_price = entry + tp_pips * pip if side == "BUY" else entry - tp_pips * pip
        sl_price = entry - sl_pips * pip if side == "BUY" else entry + sl_pips * pip

        label = "flat"
        pnl_pips = 0.0
        
        for _, bar in window.iterrows():
            hi = float(bar["High"])
            lo = float(bar["Low"])
            if side == "BUY":
                if hi >= tp_price:
                    label, pnl_pips = "win", tp_pips
                    break
                if lo <= sl_price:
                    label, pnl_pips = "loss", -sl_pips
                    break
            else:
                if lo <= tp_price:
                    label, pnl_pips = "win", tp_pips
                    break
                if hi >= sl_price:
                    label, pnl_pips = "loss", -sl_pips
                    break
        else:
            last_close = float(window["Close"].iloc[-1])
            move = (last_close - entry) if side == "BUY" else (entry - last_close)
            pnl_pips = move / pip

        df.at[idx, "label"] = label
        df.at[idx, "label_pnl_pips"] = "%.2f" % pnl_pips
        updated += 1

    # Mark traded signals
    try:
        _tp = _P("trades.csv")
        if _tp.exists():
            _tr_df = pd.read_csv(_tp)
            if len(_tr_df) and "opened_utc" in _tr_df.columns:
                _tr_df["opened_utc"] = pd.to_datetime(_tr_df["opened_utc"], utc=True, errors="coerce")
                _sig_ts = pd.to_datetime(df["ts_utc"], utc=True, errors="coerce")
                _marked = 0
                for _, _t in _tr_df.iterrows():
                    _m = (df["symbol"] == _t["symbol"]) & ((_sig_ts - _t["opened_utc"]).abs() < pd.Timedelta(seconds=10))
                    if _m.any() and (df.loc[_m, "traded"] != "Y").any():
                        df.loc[_m, "traded"] = "Y"
                        _marked += int(_m.sum())
                if _marked:
                    log("  Marked %d traded signal(s)" % _marked)
    except Exception as _e:
        log("  mark traded failed: %s" % _e)

    df.to_csv(path, index=False)
'''

s = s[:start_idx] + new_func + s[end_idx:]
open(p, "w").write(s)
print("✅ Rewrote label_signals perfectly!")
