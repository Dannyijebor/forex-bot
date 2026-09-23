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
    print(line, flush=True)


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


def safety_guards_pass(symbol, today_trades):
    daily_cap = getattr(cfg, "MAX_TRADES_PER_DAY", 100)
    if len(today_trades) >= daily_cap:
        log("  Global daily cap (%d/%d)." % (len(today_trades), daily_cap))
        return False

    if "symbol" in today_trades.columns and len(today_trades) > 0:
        sym_count = (today_trades["symbol"] == symbol).sum()
        sym_cap = getattr(cfg, "MAX_TRADES_PER_SYMBOL_PER_DAY", 3)
        if sym_count >= sym_cap:
            log("  Per-symbol cap %s (%d/%d)." % (symbol, sym_count, sym_cap))
            return False

    hourly_cap = getattr(cfg, "MAX_TRADES_PER_HOUR", 2)
    if "opened_utc" in today_trades.columns and len(today_trades) > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
        recent = today_trades[today_trades["opened_utc"] >= cutoff]
        if len(recent) >= hourly_cap:
            log("  Hourly cap (%d/%d)." % (len(recent), hourly_cap))
            return False

    max_streak = getattr(cfg, "MAX_CONSECUTIVE_LOSSES", 2)
    if "pnl_usd" in today_trades.columns and len(today_trades) > 0:
        closed = today_trades.dropna(subset=["pnl_usd"]).sort_values("opened_utc")
        streak = 0
        for pnl in closed["pnl_usd"].iloc[::-1]:
            if pnl <= 0:
                streak += 1
            else:
                break
        if streak >= max_streak:
            log("  Loss streak %d/%d - pausing." % (streak, max_streak))
            return False

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


def manage_positions(client, aid, open_positions):
    if not open_positions:
        return

    # --- Check 1: Collective profit guard ---
    collective_tp = getattr(cfg, "COLLECTIVE_TP_USD", 10.0)
    total_profit = sum((getattr(p, "profit", 0) or 0) for p in open_positions)
    if total_profit >= collective_tp:
        log("  COLLECTIVE TP: total unrealized $%.2f >= $%.2f" % (total_profit, collective_tp))
        closed = 0
        for p in open_positions:
            profit = getattr(p, "profit", 0) or 0
            if profit > 0:
                if close_position(client, aid, p.ticket, "collective_tp"):
                    closed += 1
        log("  Closed %d profitable positions" % closed)
        return

    # --- Check 2: Individual trade: age > 1 min AND profit >= $3 ---
    min_hold = getattr(cfg, "PROFIT_HOLD_MINUTES", 1)
    min_profit = getattr(cfg, "PROFIT_TAKE_USD", 3.0)
    for p in open_positions:
        open_time = getattr(p, "open_time", None)
        if not open_time:
            continue
        try:
            ot = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
            age_min = (datetime.now(timezone.utc) - ot).total_seconds() / 60
            profit = getattr(p, "profit", 0) or 0
            if age_min >= min_hold and profit >= min_profit:
                log("  PROFIT TAKE: %s age=%.1fmin profit=$%.2f" % (p.ticket, age_min, profit))
                close_position(client, aid, p.ticket, "time_profit")
        except Exception as e:
            log("  Hold check: %s" % e)


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

        # 3. Score all symbols
        threshold_boost, win_rate, adaptive_state = compute_adaptive_boost(client, aid)
        log("  ADAPTIVE: state=%s win_rate=%.2f boost=%+.3f" % (adaptive_state, win_rate, threshold_boost))
        results = score_all(pairs, cross_daily, boost=threshold_boost)
        if not results:
            log("  No scoring results.")
            return

        for r in results:
            buy_m = "Y" if r["buy_qualifies"] else "n"
            sell_m = "Y" if r["sell_qualifies"] else "n"
            log("  %s: UP p=%.3f m=%.3f/%.2f %s | DOWN p=%.3f m=%.3f/%.2f %s" % (
                r["symbol"],
                r["primary_up"], r["meta_up"], r["thr_up"], buy_m,
                r["primary_down"], r["meta_down"], r["thr_down"], sell_m,
            ))

        # 4. Account state + position management (ALWAYS runs)
        acct = client.accounts.get(aid)
        equity = acct.account.equity
        open_positions = acct.positions or []
        log("  Equity $%.2f  Positions %d" % (equity, len(open_positions)))

        manage_positions(client, aid, open_positions)

        # Refresh state after possible closes
        acct = client.accounts.get(aid)
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
