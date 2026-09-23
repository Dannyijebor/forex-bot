"""auto_trader.py — V5: 3-symbol BUY+SELL meta-labeled trading."""
import os, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v5 import (
    load_cross_assets, fetch_all_pairs, score_all, pick_best,
)
import trader_config as cfg

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from tickerall import Tickerall

load_dotenv(os.path.expanduser("~/forex_model/.env"))
if not os.getenv("TICKERALL_API_KEY"):
    load_dotenv(os.path.expanduser("~/forex-bot-clean/.env"))

LOCK = Path(".auto_trader.lock")
LAST_BAR_FILE = Path(".last_traded_bar")


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)


def notify(title, content):
    if os.path.exists("/data/data/com.termux/files/usr/bin/termux-notification"):
        os.system(f'termux-notification --title "{title}" --content "{content}" --priority high')
    else:
        print(f"[NOTIFY] {title}: {content}")


def kill_switch_active():
    return Path(cfg.KILL_FILE).exists()


def load_todays_trades():
    p = Path(cfg.TRADES_CSV)
    if not p.exists(): return pd.DataFrame()
    df = pd.read_csv(p)
    if df.empty: return df
    df["opened_utc"] = pd.to_datetime(df["opened_utc"], format="mixed", utc=True)
    today = datetime.now(timezone.utc).date()
    return df[df["opened_utc"].dt.date == today]


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
        log(f"  Closed {ticket} ({reason}): {r.closed}")
        return True
    except Exception as e:
        log(f"  Close {ticket} failed: {e}")
        return False


def size_by_confidence(prob, base=0.10):
    if prob >= 0.80: mult = 3.0
    elif prob >= 0.70: mult = 2.0
    elif prob >= 0.60: mult = 1.5
    else: mult = 1.0
    return max(0.01, min(round(base * mult, 2), 0.5))


def compute_tp_sl(price, atr_frac, pip, side,
                  tp_mult=2.0, sl_mult=1.0,
                  min_tp=8.0, min_sl=4.0, max_tp=25.0, max_sl=10.0):
    atr_price = atr_frac * price
    atr_pips = atr_price / pip
    tp_pips = max(min_tp, min(atr_pips * tp_mult, max_tp))
    sl_pips = max(min_sl, min(atr_pips * sl_mult, max_sl))
    if side == "BUY":
        tp = round(price + tp_pips * pip, 5)
        sl = round(price - sl_pips * pip, 5)
    else:
        tp = round(price - tp_pips * pip, 5)
        sl = round(price + sl_pips * pip, 5)
    return tp, sl, tp_pips, sl_pips


def main():
    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        if age < 240:
            log(f"Locked ({age:.0f}s).")
            return
    LOCK.touch()

    try:
        if kill_switch_active():
            log("KILL switch active.")
            return

        cross_daily = load_cross_assets()
        pairs = fetch_all_pairs(days=7)
        if any(p is None for p in pairs.values()):
            log("Data fetch failed.")
            return

        results = score_all(pairs, cross_daily)
        if not results:
            log("No scoring results.")
            return

        for r in results:
            buy_m = "Y" if r["buy_qualifies"] else "n"
            sell_m = "Y" if r["sell_qualifies"] else "n"
            log(f"  {r['symbol']}: UP meta={r['meta_up']:.4f} thr={r['thr_up']} {buy_m} | DOWN meta={r['meta_down']:.4f} thr={r['thr_down']} {sell_m}")

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

        log(f"  Best: {symbol} {side} @ meta={prob:.4f}")

        client = Tickerall(api_key=os.getenv("TICKERALL_API_KEY"))
        session = None
        for attempt in range(3):
            try:
                session = client.sessions.start(
                    broker="mt5", server=os.getenv("EXNESS_SERVER"),
                    account=int(os.getenv("EXNESS_LOGIN")),
                    password=os.getenv("EXNESS_PASSWORD"),
                    terminal_type="MOBILE",
                )
                break
            except Exception as e:
                log(f"  Session {attempt+1}/3 failed: {e}")
                time.sleep(5)
        if session is None:
            log("  All sessions failed.")
            return

        if not session.is_demo:
            log("LIVE ACCOUNT - refusing.")
            client.sessions.end(session.account_id)
            return

        aid = session.account_id

        try:
            acct = client.accounts.get(aid)
            equity = acct.account.equity
            open_positions = acct.positions or []
            log(f"  Equity ${equity:.2f}  Positions {len(open_positions)}")

            for p in open_positions:
                open_time = getattr(p, "open_time", None)
                if open_time:
                    try:
                        ot = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
                        age_min = (datetime.now(timezone.utc) - ot).total_seconds() / 60
                        if age_min > cfg.MAX_HOLD_MINUTES:
                            profit = getattr(p, "profit", 0) or 0
                            if profit > 0:
                                log(f"  Closing {p.ticket} (age {age_min:.0f}min)")
                                close_position(client, aid, p.ticket, "time_profit")
                    except Exception as e:
                        log(f"  Hold check: {e}")

            acct = client.accounts.get(aid)
            open_positions = acct.positions or []
            equity = acct.account.equity

            if not in_trading_window():
                log(f"  Outside window.")
                return
            if len(open_positions) >= cfg.MAX_POSITIONS:
                log(f"  Max positions.")
                return
            today_trades = load_todays_trades()
            if len(today_trades) >= cfg.MAX_TRADES_PER_DAY:
                log(f"  Daily cap.")
                return

            bar_key = str(bar_ts)
            if LAST_BAR_FILE.exists() and LAST_BAR_FILE.read_text().strip() == bar_key:
                log(f"  Already traded bar.")
                return

            volume = size_by_confidence(prob, base=cfg.BASE_VOLUME)
            max_risk_usd = equity * 0.05
            max_lots_by_risk = max_risk_usd / (4.0 * 10.0)
            volume = round(min(volume, max_lots_by_risk), 2)
            volume = max(volume, cfg.LOT_MIN)

            tp, sl, tp_pips, sl_pips = compute_tp_sl(price, atr_frac, pip, side)

            log(f"  SIGNAL {side} {symbol} @ {price:.5f} meta={prob:.3f}")
            log(f"      Vol={volume}  TP={tp}  SL={sl}")

            try:
                result = client.orders.place(
                    aid, type="market", symbol=tickerall_symbol, side=side,
                    volume=volume, stop_loss=sl, take_profit=tp,
                    comment=f"{symbol}-{side[0]}-m{prob:.2f}",
                    timeout=90.0,
                )
            except Exception as oe:
                log(f"  Order failed: {type(oe).__name__}: {oe}")
                return

            LAST_BAR_FILE.write_text(bar_key)
            log(f"  Placed: ticket={result.ticket} status={result.status}")

            log_trade({
                "opened_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol, "side": side,
                "bar_utc": bar_ts.isoformat() if hasattr(bar_ts, "isoformat") else str(bar_ts),
                "primary_up": round(r["primary_up"], 4),
                "primary_down": round(r["primary_down"], 4),
                "meta_up": round(r["meta_up"], 4),
                "meta_down": round(r["meta_down"], 4),
                "ticket": result.ticket,
                "entry_price": result.price,
                "tp": tp, "sl": sl,
                "volume": volume,
                "equity_before": equity,
            })
            notify("Trade Placed", f"{symbol} {side} #{result.ticket}")

        except Exception as e:
            log(f"  Cycle error: {type(e).__name__}: {e}")
        finally:
            try: client.sessions.end(aid)
            except: pass
    finally:
        if LOCK.exists(): LOCK.unlink()


if __name__ == "__main__":
    main()
