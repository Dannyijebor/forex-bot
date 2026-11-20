import logging

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(message)s',
    handlers=[
        logging.FileHandler("auto_trader.log"),
        logging.StreamHandler()
    ]
)
# Override print to log to file and console
print = logging.info

"""auto_trader.py — V5.1: live MT5 data + fill-price stops."""
import os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v5 import (
    load_cross_assets, fetch_all_pairs_live, score_all, pick_best,
)
import trader_config as cfg

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from tickerall import Tickerall

load_dotenv(os.path.expanduser("~/Forex_model/.env"))
if not os.getenv("TICKERALL_API_KEY"):
    load_dotenv(os.path.expanduser("~/forex_model/.env"))
if not os.getenv("TICKERALL_API_KEY"):
    load_dotenv(os.path.expanduser("~/forex-bot-clean/.env"))

LOCK = Path(".auto_trader.lock")
LAST_BAR_FILE = Path(".last_traded_bar")


def log(msg):
    line = "[%s] %s" % (datetime.now(timezone.utc).isoformat(), msg)
    print(line)


def notify(title, content):
    if os.path.exists("/data/data/com.termux/files/usr/bin/termux-notification"):
        os.system('termux-notification --title "%s" --content "%s" --priority high' % (title, content))
    else:
        print("[NOTIFY] %s: %s" % (title, content))


def kill_switch_active():
    return Path(cfg.KILL_FILE).exists()


def load_todays_trades():
    p = Path(cfg.TRADES_CSV)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    if df.empty:
        return df
    try:
        df["opened_utc"] = pd.to_datetime(df["opened_utc"], format="mixed", utc=True)
        today = datetime.now(timezone.utc).date()
        return df[df["opened_utc"].dt.date == today]
    except Exception:
        return pd.DataFrame()


def in_trading_window():
    h = datetime.now(timezone.utc).hour
    return cfg.TRADE_HOURS_UTC_START <= h < cfg.TRADE_HOURS_UTC_END


def log_trade(row):
    p = Path(cfg.TRADES_CSV)
    df = pd.DataFrame([row])
    df.to_csv(p, mode="a", header=not p.exists(), index=False)


def close_position(client, aid, ticket, reason):
    try:
        r = client.positions.close(aid, ticket=int(ticket))
        log("  Closed %s (%s): %s" % (ticket, reason, r.closed))
        return True
    except Exception as e:
        log("  Close %s failed: %s" % (ticket, e))
        return False


def size_by_confidence(prob, base=0.06):
    if prob >= 0.80:
        mult = 3.0
    elif prob >= 0.70:
        mult = 2.0
    elif prob >= 0.60:
        mult = 1.5
    else:
        mult = 1.0
    return max(0.01, min(round(base * mult, 2), 0.60))


def compute_tp_sl(price, atr_frac, pip, side,
                  min_tp=15.0, min_sl=10.0,
                  max_tp=30.0, max_sl=15.0):
    atr_price = atr_frac * price
    atr_pips = atr_price / pip
    tp_pips = max(min_tp, min(atr_pips * 2.0, max_tp))
    sl_pips = max(min_sl, min(atr_pips * 1.0, max_sl))
    if side == "BUY":
        tp = round(price + tp_pips * pip, 5)
        sl = round(price - sl_pips * pip, 5)
    else:
        tp = round(price - tp_pips * pip, 5)
        sl = round(price + sl_pips * pip, 5)
    return tp, sl, tp_pips, sl_pips


def compute_loss_streak_penalty(today_trades, now_utc):
    """Return (penalty, streak, minutes_since_last_loss).

    Consecutive losses beyond MAX_CONSECUTIVE_LOSSES add a threshold penalty
    that decays over time. A win resets the streak. HARD_BLOCK stops the day.
    """
    if today_trades is None or len(today_trades) == 0:
        return (0.0, 0, None)
    if "pnl_usd" not in today_trades.columns:
        return (0.0, 0, None)
    closed = today_trades.dropna(subset=["pnl_usd"]).sort_values("opened_utc")
    if len(closed) == 0:
        return (0.0, 0, None)
    streak = 0
    for pnl in closed["pnl_usd"].iloc[::-1]:
        if pnl <= 0:
            streak += 1
        else:
            break
    if streak < getattr(cfg, "MAX_CONSECUTIVE_LOSSES", 2):
        return (0.0, streak, None)
    try:
        last_loss_time = pd.to_datetime(closed["opened_utc"].iloc[-1], utc=True)
        minutes_since = (now_utc - last_loss_time).total_seconds() / 60.0
    except Exception:
        minutes_since = 0.0
    base = getattr(cfg, "LOSS_STREAK_PENALTY", 0.08)
    hold = getattr(cfg, "LOSS_STREAK_HOLD_MIN", 10)
    halflife = getattr(cfg, "LOSS_STREAK_DECAY_HALFLIFE_MIN", 10)
    zero = getattr(cfg, "LOSS_STREAK_PENALTY_ZERO", 0.005)
    if minutes_since < hold:
        penalty = base
    else:
        steps = (minutes_since - hold) / max(halflife, 1)
        penalty = base * (0.5 ** steps)
    if penalty < zero:
        penalty = 0.0
    return (penalty, streak, minutes_since)


def safety_guards_pass(symbol, today_trades):
    daily_cap = getattr(cfg, "MAX_TRADES_PER_DAY", 100)
    if len(today_trades) >= daily_cap:
        log("  Global daily cap (%d/%d)." % (len(today_trades), daily_cap))
        return False

    # Session-aware scaling of caps
    sym_mult = 1.0
    hourly_cap = getattr(cfg, "MAX_TRADES_PER_HOUR", 2)
    if getattr(cfg, "SESSION_SCALING_ENABLED", False):
        try:
            _gname, sym_mult, hourly_cap, _gactive = cfg.session_profile(datetime.now(timezone.utc))
        except Exception as _ge:
            log("  session_profile failed: %s" % _ge)
            sym_mult = 1.0

    if "symbol" in today_trades.columns and len(today_trades) > 0:
        sym_count = (today_trades["symbol"] == symbol).sum()
        base_sym_cap = getattr(cfg, "MAX_TRADES_PER_SYMBOL_PER_DAY", 15)
        sym_cap = max(1, int(round(base_sym_cap * sym_mult)))
        if sym_count >= sym_cap:
            log("  Per-symbol cap %s (%d/%d, mult=%.1f)" % (symbol, sym_count, sym_cap, sym_mult))
            return False
    if "opened_utc" in today_trades.columns and len(today_trades) > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = today_trades[today_trades["opened_utc"] >= cutoff]
        if len(recent) >= hourly_cap:
            log("  Hourly cap (%d/%d)." % (len(recent), hourly_cap))
            return False

    hard_streak = getattr(cfg, "LOSS_STREAK_HARD_BLOCK", 4)
    hard_cooldown = getattr(cfg, "LOSS_STREAK_HARD_BLOCK_COOLDOWN_MIN", 120)
    if "pnl_usd" in today_trades.columns and len(today_trades) > 0:
        closed = today_trades.dropna(subset=["pnl_usd"]).sort_values("opened_utc")
        streak = 0
        for pnl in closed["pnl_usd"].iloc[::-1]:
            if pnl <= 0:
                streak += 1
            else:
                break
        if streak >= hard_streak:
            # Cooldown, not full-day pause
            try:
                last_loss_time = pd.to_datetime(closed["opened_utc"].iloc[-1], utc=True)
                mins_since = (datetime.now(timezone.utc) - last_loss_time).total_seconds() / 60.0
            except Exception:
                mins_since = 0.0
            if mins_since < hard_cooldown:
                log("  HARD loss streak %d/%d - %.0f min cooldown remaining." % (
                    streak, hard_streak, hard_cooldown - mins_since))
                return False
            else:
                log("  HARD loss streak %d/%d expired (%.0f min elapsed) - resuming." % (
                    streak, hard_streak, mins_since))

    return True


def open_session():
    client = Tickerall(api_key=os.getenv("TICKERALL_API_KEY"))
    for attempt in range(3):
        try:
            session = client.sessions.start(
                broker="mt5", server=os.getenv("EXNESS_SERVER"),
                account=int(os.getenv("EXNESS_LOGIN")),
                password=os.getenv("EXNESS_PASSWORD"),
                terminal_type="MOBILE",
            )
            return client, session
        except Exception as e:
            log("  Session %d/3 failed: %s" % (attempt + 1, e))
            time.sleep(5)
    return None, None



# --- WORLD CLASS UPGRADE: MACRO NEWS BLACKOUTS ---
# Hardcoded high-impact forex news windows (UTC Time)
# 13:30 UTC = US CPI / NFP, 18:00 UTC = FOMC, 11:00 UTC = ECB
NEWS_BLACKOUT_HOURS = [13, 18, 11]

def is_news_blackout(now_utc):
    if now_utc.hour in NEWS_BLACKOUT_HOURS:
        return True
    return False
# ------------------------------------------------


# --- QUANTUM UPGRADE: CONTRARIAN FLIP & ATR RISK ---
CONTRARIAN_BUY_PAIRS = ["EURUSD", "GBPUSD"] # The models proven to be anti-predictive

def get_dynamic_sl_tp(df, side):
    # Calculate 14-period ATR for dynamic risk sizing
    tr = pd.concat([df['High'] - df['Low'], 
                    (df['High'] - df['Close'].shift()).abs(), 
                    (df['Low'] - df['Close'].shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    
    # Scale TP and SL based on current volatility
    if pd.isna(atr) or atr == 0: return 15.0, 10.0 # fallback
    
    # Convert ATR to pips (approx)
    pip = 0.01 if df['Close'].iloc[-1] > 100 else 0.0001
    atr_pips = atr / pip
    
    # Risk 1.0x ATR, Reward 2.0x ATR (1:2 Risk/Reward)
    # SWING MODE: Aim for 3x ATR on TP, 1.5x ATR on SL. 
    # If ATR is small (quiet market), fallback to a minimum of 40 pips TP / 25 pips SL.
    return max(40.0, atr_pips * 3.0), max(25.0, atr_pips * 1.5)

def apply_contrarian_logic(symbol, side):
    # COUNCIL CHAMPION LOGIC
    champ_dna = COUNCIL_STATE["champion"]["dna"]
    flip_allowed = champ_dna.get("flip_buy", 1)

    if symbol in CONTRARIAN_BUY_PAIRS and side == "BUY" and flip_allowed == 1:
        print(f"  ⚠️ CONTRARIAN FLIP: Primary model wanted BUY on {symbol}. Flipping to SELL.")
        return "SELL"
    return side
# ---------------------------------------------------


# --- ULTIMATE UPGRADE: KELLY CRITERION SIZING ---
def calculate_kelly_lot(base_lot, meta_confidence):
    # If confidence is below 50%, don't trade. If it's 50-60%, trade small.
    # If it's 80%+, scale the lot size up dramatically.
    if meta_confidence < 0.50:
        return 0.0
    elif meta_confidence < 0.60:
        return round(base_lot * 0.5, 2) # Half size
    elif meta_confidence < 0.75:
        return base_lot # Normal size
    else:
        return round(base_lot * 2.0, 2) # Double size for A+ setups
# --------------------------------------------------


import json
import os

# --- QUANTUM THOUGHT PROCESSOR ---
QUANTUM_DNA = {}
if os.path.exists("winning_dna.json"):
    with open("winning_dna.json", "r") as f:
        QUANTUM_DNA = json.load(f)
        print(f"  [Quantum] Loaded Evolved DNA: {QUANTUM_DNA}")
# --------------------------------


import json
# --- COUNCIL OF MODELS: CHAMPION STATE ---
COUNCIL_STATE = {"champion": {"dna": {"thresh": 0.65, "flip_buy": 1}}}
if os.path.exists("council_state.json"):
    with open("council_state.json", "r") as f:
        COUNCIL_STATE = json.load(f)
        print(f"  [Council] Active Champion: {COUNCIL_STATE['champion']['id']} | DNA: {COUNCIL_STATE['champion']['dna']}")
# -----------------------------------------


# --- IRONCLAD DEFENSE: DAILY DRAWDOWN CIRCUIT BREAKER ---
DAILY_DRAWDOWN_LIMIT = -15.0 # Stop trading if we lose $15 in one day

def check_daily_drawdown():
    try:
        t = pd.read_csv("trades.csv")
        if len(t) == 0: return True
        t['opened_utc'] = pd.to_datetime(t['opened_utc'], utc=True)
        today = pd.Timestamp.utcnow().date()
        today_trades = t[t['opened_utc'].dt.date == today]
        daily_pnl = today_trades['pnl_usd'].sum()
        if daily_pnl <= DAILY_DRAWDOWN_LIMIT:
            print(f"  🚨 CIRCUIT BREAKER: Daily loss hit {daily_pnl:.2f} USD. Halting trading.")
            return False
        return True
    except Exception as e:
        return True

# Safe Risk Parity Check (Will not crash if open trades are unknown)
def check_correlation_risk(sym, current_open_trades=None):
    return 1.0 # Default multiplier
# ---------------------------------------------------------


# --- SWING UPGRADE: TRADE COOLDOWN ---
TRADE_COOLDOWN_MINUTES = 60

def is_on_cooldown(symbol):
    try:
        t = pd.read_csv("trades.csv")
        if len(t) == 0: return False
        t['opened_utc'] = pd.to_datetime(t['opened_utc'], utc=True)
        sym_trades = t[t['symbol'] == symbol].sort_values('opened_utc')
        if len(sym_trades) == 0: return False
        
        last_trade_time = sym_trades.iloc[-1]['opened_utc']
        now = pd.Timestamp.utcnow()
        mins_since = (now - last_trade_time).total_seconds() / 60
        
        if mins_since < TRADE_COOLDOWN_MINUTES:
            return True
        return False
    except Exception:
        return False
# -------------------------------------

def compute_adaptive_boost(client=None, aid=None):
    """Read most recent closed trades from Exness (newest-first from API)."""
    closed = []
    if client is not None and aid is not None:
        try:
            history = client.history.get(aid)
            # API returns newest-first: history[0] = most recent
            for h in history[:20]:
                pnl = ((getattr(h, "profit", 0) or 0)
                       + (getattr(h, "commission", 0) or 0)
                       + (getattr(h, "swap", 0) or 0))
                closed.append(float(pnl))
        except Exception as e:
            print("  adaptive history failed: %s" % e)
            closed = []

    print("  adaptive saw %d trades, newest5=%s" % (len(closed), closed[:5]))

    if len(closed) < 3:
        return 0.0, 0.0, "warming_up"

    window = getattr(cfg, "ADAPTIVE_WINDOW", 5)
    recent = closed[:window]   # <-- NEWEST 5 (was closed[-window:])
    win_rate = sum(1 for p in recent if p > 0) / len(recent)

    step = getattr(cfg, "ADAPTIVE_STEP", 0.02)
    loosen = getattr(cfg, "ADAPTIVE_LOOSEN_THRESHOLD", 0.60)
    tighten = getattr(cfg, "ADAPTIVE_TIGHTEN_THRESHOLD", 0.40)
    max_boost = getattr(cfg, "ADAPTIVE_MAX_PRIMARY", 0.50) - 0.42

    if win_rate >= loosen:
        boost = min(step * 2, max_boost)
        state = "loosen"
    elif win_rate <= tighten:
        boost = -step
        state = "tighten"
    else:
        boost = 0.0
        state = "neutral"

    return float(boost), float(win_rate), state


def log_signal(signal_dict):
    """Append one row per symbol per tick to signals_log.csv."""
    import csv
    from pathlib import Path as _P
    path = _P("signals_log.csv")
    fields = ["ts_utc","symbol","regime","primary_up","primary_down",
              "meta_up","meta_down","thr_primary","thr_meta_up","thr_meta_down",
              "boost","penalty","buy_ok","sell_ok","traded","skip_reason",
              "label","label_pnl_pips"]
    exists = path.exists()
    try:
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            if not exists:
                w.writeheader()
            w.writerow({k: signal_dict.get(k, "") for k in fields})
    except Exception as e:
        log("  log_signal failed: %s" % e)


def label_signals(pairs, lookahead_min=240, pip_sizes=None):
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
    if updated:
        log("  Labelled %d signal(s)" % updated)


def check_model_invalidation(client, aid, open_positions, results):
    """Close losing positions when the model's meta score for their direction
    drops well below the threshold that triggered entry."""
    if not getattr(cfg, "MODEL_AWARE_EXIT_ENABLED", False):
        return
    if not open_positions or not results:
        return

    min_age = getattr(cfg, "MODEL_AWARE_EXIT_MIN_AGE_MIN", 2)
    max_loss = getattr(cfg, "MODEL_AWARE_EXIT_MAX_LOSS_USD", 8.0)
    buffer   = getattr(cfg, "MODEL_AWARE_EXIT_META_BUFFER", 0.05)

    for p in open_positions:
        profit = getattr(p, "profit", 0) or 0
        if profit >= 0:
            continue  # only manage losers
        if abs(profit) > max_loss:
            continue  # too late, let SL handle it

        ot = getattr(p, "open_time", None)
        if not ot:
            continue
        try:
            otd = datetime.fromisoformat(ot.replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - otd).total_seconds() / 60.0
        except Exception:
            continue
        if age_min < min_age:
            continue

        sym = (p.symbol or "").replace("m", "").replace("M", "")
        r = next((x for x in results if x.get("symbol") == sym), None)
        if r is None:
            continue

        side = (p.side or "").upper()
        if side == "BUY":
            meta = r.get("meta_up", 0.0)
            thr  = r.get("thr_up", 0.0)
        elif side == "SELL":
            meta = r.get("meta_down", 0.0)
            thr  = r.get("thr_down", 0.0)
        else:
            continue

        if meta < (thr - buffer):
            log("  MODEL FLIP: %s %s %s age=%.1fmin pnl=$%.2f meta=%.3f < thr-buf=%.3f" % (
                p.ticket, sym, side, age_min, profit, meta, thr - buffer))
            close_position(client, aid, p.ticket, "model_flip")


def manage_positions(client, aid, open_positions, results=None):
    if not open_positions:
        return

    # --- Check 0: Model-aware early exit for losing trades ---
    check_model_invalidation(client, aid, open_positions, results)

    # --- Check 1: Collective profit guard (raised, requires 2+ positions) ---
    collective_tp = getattr(cfg, "COLLECTIVE_TP_USD", 50.0)
    profitable = [p for p in open_positions if (getattr(p, "profit", 0) or 0) > 0]
    total_profit = sum((getattr(p, "profit", 0) or 0) for p in open_positions)
    if total_profit >= collective_tp and len(profitable) >= 2:
        log("  COLLECTIVE TP: total $%.2f >= $%.2f across %d positions" % (
            total_profit, collective_tp, len(profitable)))
        closed = 0
        for p in profitable:
            if close_position(client, aid, p.ticket, "collective_tp"):
                closed += 1
        log("  Closed %d profitable positions" % closed)
        return

    # --- Check 2: Size-aware individual profit-take ---
    min_hold = getattr(cfg, "PROFIT_HOLD_MINUTES", 5)
    per_vol = getattr(cfg, "PROFIT_TAKE_PER_VOLUME", 80.0)
    for p in open_positions:
        ot = getattr(p, "open_time", None)
        if not ot:
            continue
        try:
            otd = datetime.fromisoformat(ot.replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - otd).total_seconds() / 60
            profit = getattr(p, "profit", 0) or 0
            volume = float(getattr(p, "volume", 0.1) or 0.1)
            profit_target = max(5.0, volume * per_vol)
            if age_min >= min_hold and profit >= profit_target:
                log("  PROFIT TAKE: %s age=%.1fmin vol=%.2f pnl=$%.2f >= $%.2f" % (
                    p.ticket, age_min, volume, profit, profit_target))
                close_position(client, aid, p.ticket, "time_profit")
        except Exception as e:
            log("  Hold check: %s" % e)


def safe_account_snapshot(client, aid):
    """Return account object or None. Never raises."""
    try:
        a = client.accounts.get(aid)
        if a is None:
            return None
        if getattr(a, "account", None) is None:
            return None
        return a
    except Exception as e:
        log("  account fetch failed: %s" % e)
        return None


def reconcile_closed_trades(client, aid):
    """Fill pnl_usd in trades.csv for tickets that have closed on Exness."""
    p = Path("trades.csv")
    if not p.exists():
        return
    try:
        df = pd.read_csv(p)
    except Exception as e:
        log("  reconcile: read failed: %s" % e)
        return
    if "ticket" not in df.columns or "pnl_usd" not in df.columns:
        return

    acct = client.accounts.get(aid)
    open_tickets = {str(x.ticket) for x in (acct.positions or [])}

    mask = df["pnl_usd"].isna() & ~df["ticket"].astype(str).isin(open_tickets)
    if not mask.any():
        return

    history = client.history.get(aid) or []
    pnl_by_ticket = {}
    for h in history:
        t = str(getattr(h, "ticket", "") or "")
        if not t or not getattr(h, "complete", True):
            continue
        pnl = float(
            (getattr(h, "profit", 0) or 0)
            + (getattr(h, "commission", 0) or 0)
            + (getattr(h, "swap", 0) or 0)
        )
        pnl_by_ticket[t] = pnl_by_ticket.get(t, 0.0) + pnl

    updated = 0
    for idx in df.index[mask]:
        t = str(df.at[idx, "ticket"])
        if t in pnl_by_ticket:
            df.at[idx, "pnl_usd"] = pnl_by_ticket[t]
            updated += 1

    if updated:
        df.to_csv(p, index=False)
        log("  Reconciled %d closed trade(s) into trades.csv" % updated)


def main():
    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        if age < 240:
            log("Locked (%.0fs)." % age)
            return
    LOCK.touch()

    client = None
    aid = None

    try:
        if kill_switch_active():
            log("KILL switch active.")
            return

        # 0. Session-aware gate (skip weekends, log current session)
        if getattr(cfg, "SESSION_SCALING_ENABLED", False):
            _sname, _smult, _shcap, _sactive = cfg.session_profile(datetime.now(timezone.utc))
            log("  Session: %s (sym_mult=%.1f, hourly=%d, active=%s)" % (_sname, _smult, _shcap, _sactive))
            if not _sactive:
                log("  Not trading (%s). Exiting." % _sname)
                return

        # 1. Open broker session FIRST
        client, session = open_session()
        if client is None or session is None:
            log("All sessions failed.")
            return
        if not session.is_demo:
            log("LIVE ACCOUNT - refusing.")
            client.sessions.end(session.account_id)
            return
        aid = session.account_id

        # 1b. Reconcile closed trades into trades.csv before anything else
        try:
            reconcile_closed_trades(client, aid)
        except Exception as e:
            log("  reconcile failed: %s" % e)

        # 2. Fetch live bars from MT5
        log("Fetching live MT5 bars...")
        cross_daily = load_cross_assets()
        pairs = fetch_all_pairs_live(client, aid, count=1500)
        if any(p is None for p in pairs.values()):
            log("  Live data fetch failed for at least one pair.")
            return
        for sym, df in pairs.items():
            if df is not None:
                log("    %s: %d bars, last=%s" % (sym, len(df), df.index[-1]))

        # 2a. Cache bars for future retraining
        try:
            from bars_cache import cache_bars
            cache_bars(pairs)
        except Exception as e:
            log("  cache_bars failed: %s" % e)

        # 2b. Label pending signals using fetched bars
        try:
            label_signals(pairs)
        except Exception as e:
            log("  label_signals failed: %s" % e)

        # 3. Score all symbols
        threshold_boost, win_rate, adaptive_state = compute_adaptive_boost(client, aid)
        try:
            import adaptive_engine as _ae
            _ae.update_state()
        except Exception as _e:
            log("  adaptive_engine.update failed: %s" % _e)
        log("  ADAPTIVE: state=%s win_rate=%.2f boost=%+.3f" % (adaptive_state, win_rate, threshold_boost))
        _streak_trades = load_todays_trades()
        _penalty, _streak, _mins_since = compute_loss_streak_penalty(
            _streak_trades, datetime.now(timezone.utc))
        if _streak >= 1:
            _mins_str = ("%.0f" % _mins_since) if _mins_since is not None else "n/a"
            log("  Loss streak=%d, penalty=+%.3f (last loss %s min ago)" % (
                _streak, _penalty, _mins_str))
        results = score_all(pairs, cross_daily, boost=threshold_boost, penalty=_penalty)
        if not results:
            log("  No scoring results.")
            return

        for r in results:
            buy_m = "Y" if r["buy_qualifies"] else "n"
            sell_m = "Y" if r["sell_qualifies"] else "n"
            regime = r.get("regime", "?")
            log("  %s [%s]: UP p=%.3f m=%.3f/%.2f %s | DOWN p=%.3f m=%.3f/%.2f %s" % (
                r["symbol"], regime,
                r["primary_up"], r["meta_up"], r["thr_up"], buy_m,
                r["primary_down"], r["meta_down"], r["thr_down"], sell_m,
            ))

        # NEW: persist every signal to signals_log.csv (for offline training)
        _sig_ts = datetime.now(timezone.utc).isoformat()
        for r in results:
            log_signal({
                "ts_utc": _sig_ts,
                "symbol": r.get("symbol", ""),
                "regime": r.get("regime", ""),
                "primary_up": "%.4f" % r.get("primary_up", 0.0),
                "primary_down": "%.4f" % r.get("primary_down", 0.0),
                "meta_up": "%.4f" % r.get("meta_up", 0.0),
                "meta_down": "%.4f" % r.get("meta_down", 0.0),
                "thr_primary": "",
                "thr_meta_up": "%.4f" % r.get("thr_up", 0.0),
                "thr_meta_down": "%.4f" % r.get("thr_down", 0.0),
                "boost": "%.4f" % threshold_boost,
                "penalty": "%.4f" % _penalty,
                "buy_ok": "Y" if r.get("buy_qualifies") else "N",
                "sell_ok": "Y" if r.get("sell_qualifies") else "N",
                "traded": "",
                "skip_reason": "",
            })

        # 4. Account state + position management (ALWAYS runs)
        acct = safe_account_snapshot(client, aid)
        if acct is None:
            log("  Session died before account fetch — skipping cycle (will retry).")
            return
        equity = acct.account.equity
        open_positions = acct.positions or []
        log("  Equity $%.2f  Positions %d" % (equity, len(open_positions)))

        manage_positions(client, aid, open_positions, results)

        # Refresh state after possible closes
        acct = safe_account_snapshot(client, aid)
        if acct is None:
            log("  Session died after position mgmt — skipping signal.")
            return
        open_positions = acct.positions or []
        equity = acct.account.equity

        # 5. Pick best signal
        best = pick_best(results)
        if best is None:
            log("  No signal. Skipping.")
            return

        symbol, side, prob, r = best
        price = r["close"]
        bar_ts = r["timestamp"]
        atr_frac = r["atr"]
        tickerall_symbol = r["tickerall_symbol"]
        pip = r["pip_size"]

        log("  Best: %s %s @ meta=%.4f" % (symbol, side, prob))

        # 6. Guards
        today_trades = load_todays_trades()
        if not safety_guards_pass(symbol, today_trades):
            return

        # 7. Re-check limits
        if not in_trading_window():
            log("  Outside window.")
            return
        if len(open_positions) >= cfg.MAX_POSITIONS:
            log("  Max positions.")
            return

        bar_key = str(bar_ts)
        if LAST_BAR_FILE.exists() and LAST_BAR_FILE.read_text().strip() == bar_key:
            log("  Already traded bar.")
            return

        # 8. Size and place
        volume = size_by_confidence(prob, base=cfg.BASE_VOLUME)
        max_risk_usd = equity * 0.02
        max_lots_by_risk = max_risk_usd / (10.0 * 10.0)
        volume = round(min(volume, max_lots_by_risk), 2)
        volume = max(volume, cfg.LOT_MIN)

        log("  SIGNAL %s %s (Dukascopy close=%.5f) meta=%.3f" % (symbol, side, price, prob))

        # --- EXECUTION PATCH: LIVE CONTRARIAN FLIP & COOLDOWN ---
        if is_on_cooldown(symbol):
            log("  %s is on a 60-minute cooldown. Skipping live trade." % symbol)
            return
        # ---------------------------------------------------------


        try:
            result = client.orders.place(
                aid, type="market", symbol=tickerall_symbol, side=side,
                volume=volume,
                comment="%s-%s-m%.2f" % (symbol, side[0], prob),
                timeout=90.0,
            )
        except Exception as oe:
            log("  Order failed: %s: %s" % (type(oe).__name__, oe))
            return

        fill_price = float(result.price)
        tp, sl, tp_pips, sl_pips = compute_tp_sl(
            fill_price, atr_frac, pip, side,
            min_tp=getattr(cfg, "MIN_TP_PIPS", 15.0),
            min_sl=getattr(cfg, "MIN_SL_PIPS", 10.0),
            max_tp=getattr(cfg, "MAX_TP_PIPS", 30.0),
            max_sl=getattr(cfg, "MAX_SL_PIPS", 15.0),
        )
        log("      Fill=%.5f  Vol=%.2f  TP=%.5f  SL=%.5f" % (fill_price, volume, tp, sl))
        
        # --- NEW COOLDOWN PATCH: LOG TRADE IMMEDIATELY ---
        try:
            import os
            import pandas as pd
            trade_file = "trades.csv"
            trade_data = {
                "ticket": [str(result.ticket)],
                "symbol": [symbol],
                "opened_utc": [pd.Timestamp.utcnow().isoformat()],
                "pnl_usd": [None]
            }
            new_df = pd.DataFrame(trade_data)
            if os.path.exists(trade_file):
                new_df.to_csv(trade_file, mode='a', header=False, index=False)
            else:
                new_df.to_csv(trade_file, mode='w', header=True, index=False)
            log("  Logged new trade to trades.csv (Cooldown started)")
        except Exception as e:
            log("  Failed to log trade to trades.csv: %s" % e)
        # --------------------------------------------------

        try:
            client.positions.modify(
                aid, int(result.ticket),
                stop_loss=sl, take_profit=tp,
                timeout=90.0,
            )
            log("      Stops attached OK")
        except Exception as me:
            log("      Stop attach failed: %s: %s" % (type(me).__name__, me))
            try:
                client.positions.close(aid, ticket=int(result.ticket))
                log("      Closed naked position")
            except Exception:
                pass
            return

        LAST_BAR_FILE.write_text(bar_key)
        log("  Placed: ticket=%s status=%s" % (result.ticket, result.status))

        log_trade({
            "opened_utc": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "side": side,
            "bar_utc": bar_ts.isoformat() if hasattr(bar_ts, "isoformat") else str(bar_ts),
            "primary_up": round(r["primary_up"], 4),
            "primary_down": round(r["primary_down"], 4),
            "meta_up": round(r["meta_up"], 4),
            "meta_down": round(r["meta_down"], 4),
            "ticket": result.ticket,
            "entry_price": result.price,
            "tp": tp,
            "sl": sl,
            "volume": volume,
            "equity_before": equity,
        })
        notify("Trade Placed", "%s %s #%s" % (symbol, side, result.ticket))

    except Exception as e:
        log("  Cycle error: %s: %s" % (type(e).__name__, e))
    finally:
        if client is not None and aid is not None:
            try:
                client.sessions.end(aid)
            except Exception:
                pass
        if LOCK.exists():
            LOCK.unlink()


if __name__ == "__main__":
    main()
