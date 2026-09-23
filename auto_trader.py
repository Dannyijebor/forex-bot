"""
auto_trader.py — V4: 3-symbol primary + meta ensemble with cross-asset features.
Runs every 5 min via external cron. Places trade on best meta-qualified symbol.
"""
import os, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v4 import (
    load_cross_assets, fetch_all_pairs, score_all,
    META_THRESHOLDS, PIP_SIZES, TICKERALL_SYMBOLS,
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
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p)
    if df.empty:
        return df
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
        log(f"  Closed ticket {ticket} ({reason}): {r.closed}")
        return True
    except Exception as e:
        log(f"  Close failed for {ticket}: {e}")
        return False


def size_by_confidence(prob, base=0.10):
    if prob >= 0.80: mult = 3.0
    elif prob >= 0.70: mult = 2.0
    elif prob >= 0.60: mult = 1.5
    else: mult = 1.0
    lot = round(base * mult, 2)
    return max(0.01, min(lot, 0.5))


def compute_tp_sl(price, atr_frac, pip, tp_mult=2.0, sl_mult=1.0,
                  min_tp=8.0, min_sl=4.0, max_tp=25.0, max_sl=10.0):
    atr_price = atr_frac * price
    atr_pips = atr_price / pip
    tp_pips = max(min_tp, min(atr_pips * tp_mult, max_tp))
    sl_pips = max(min_sl, min(atr_pips * sl_mult, max_sl))
    return (round(price + tp_pips * pip, 5),
            round(price - sl_pips * pip, 5),
            tp_pips, sl_pips)


def main():
    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        if age < 240:
            log(f"Locked ({age:.0f}s). Exiting.")
            return
    LOCK.touch()

    try:
        if kill_switch_active():
            log("KILL switch active — no trading.")
            return

        # ── Score all symbols ──
        cross_daily = load_cross_assets()
        pairs = fetch_all_pairs(days=7)
        if any(p is None for p in pairs.values()):
            log("Data fetch failed for at least one pair.")
            return

        results = score_all(pairs, cross_daily)
        if not results:
            log("Scoring failed for all symbols.")
            return

        for r in results:
            mark = "✓" if r["qualifies"] else "✗"
            log(f"  {r['symbol']}: primary={r['primary_prob']:.4f}  "
                f"meta={r['meta_prob']:.4f}  thr={r['threshold']} {mark}")

        qualifies = [r for r in results if r["qualifies"]]
        if not qualifies:
            log("  No symbol passed meta threshold. Skipping trade.")
            return

        # Best meta confidence wins
        best = max(qualifies, key=lambda r: r["meta_prob"])
        symbol = best["symbol"]
        prob = best["meta_prob"]
        primary_prob = best["primary_prob"]
        price = best["close"]
        bar_ts = best["timestamp"]
        atr_frac = best["atr"]
        tickerall_symbol = best["tickerall_symbol"]
        pip = best["pip_size"]

        log(f"  Best: {symbol} (meta={prob:.4f}, primary={primary_prob:.4f})")

        # ── Connect to broker ──
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
                log(f"  Session attempt {attempt+1}/3 failed: {e}")
                time.sleep(5)
        if session is None:
            log("  All session attempts failed.")
            return

        if not session.is_demo:
            log("❌ LIVE ACCOUNT — refusing.")
            notify("BLOCKED", "Attempted live trade — aborted.")
            client.sessions.end(session.account_id)
            return

        aid = session.account_id

        try:
            acct = client.accounts.get(aid)
            equity = acct.account.equity
            balance = acct.account.balance
            open_positions = acct.positions or []
            log(f"  Equity ${equity:.2f}  Positions {len(open_positions)}")

            # Position management: close stale positions
            for p in open_positions:
                open_time = getattr(p, "open_time", None)
                if open_time:
                    try:
                        ot = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
                        age_min = (datetime.now(timezone.utc) - ot).total_seconds() / 60
                        if age_min > cfg.MAX_HOLD_MINUTES:
                            profit = getattr(p, "profit", 0) or 0
                            if profit > 0:
                                log(f"  Closing {p.ticket} (age {age_min:.0f}min, +${profit:.2f})")
                                close_position(client, aid, p.ticket, "time_profit")
                    except Exception as e:
                        log(f"  Hold check: {e}")

            # Re-fetch after closes
            acct = client.accounts.get(aid)
            open_positions = acct.positions or []
            equity = acct.account.equity

            # ── Safety limits ──
            if not in_trading_window():
                log(f"  Outside window ({cfg.TRADE_HOURS_UTC_START}-{cfg.TRADE_HOURS_UTC_END} UTC).")
                return

            if len(open_positions) >= cfg.MAX_POSITIONS:
                log(f"  At max positions ({cfg.MAX_POSITIONS}).")
                return

            today_trades = load_todays_trades()
            if len(today_trades) >= cfg.MAX_TRADES_PER_DAY:
                log(f"  At daily cap ({cfg.MAX_TRADES_PER_DAY}).")
                return

            # Already-traded-this-bar check
            bar_key = str(bar_ts)
            if LAST_BAR_FILE.exists() and LAST_BAR_FILE.read_text().strip() == bar_key:
                log(f"  Already traded bar {bar_key}.")
                return

            # ── Place order ──
            volume = size_by_confidence(prob, base=cfg.BASE_VOLUME)

            # Risk cap
            max_risk_usd = equity * 0.05
            max_lots_by_risk = max_risk_usd / (4.0 * 10.0)  # 4-pip SL, ~$10/pip/lot
            volume = round(min(volume, max_lots_by_risk), 2)
            volume = max(volume, cfg.LOT_MIN)

            tp, sl, tp_pips, sl_pips = compute_tp_sl(price, atr_frac, pip)

            log(f"  🎯 TRADE ({symbol} meta={prob:.3f}) — BUY @ {price:.5f}")
            log(f"      Vol={volume}  TP={tp} ({tp_pips:.1f}p)  SL={sl} ({sl_pips:.1f}p)")

            try:
                result = client.orders.place(
                    aid, type="market", symbol=tickerall_symbol, side="BUY",
                    volume=volume, stop_loss=sl, take_profit=tp,
                    comment=f"{symbol}-m{prob:.2f}",
                    timeout=90.0,
                )
            except Exception as oe:
                log(f"  Order placement failed: {type(oe).__name__}: {oe}")
                return

            LAST_BAR_FILE.write_text(bar_key)
            log(f"  Order placed: ticket={result.ticket} status={result.status} price={result.price}")

            log_trade({
                "opened_utc": datetime.now(timezone.utc).isoformat(),
                "symbol": symbol,
                "bar_utc": bar_ts.isoformat() if hasattr(bar_ts, "isoformat") else str(bar_ts),
                "primary_prob": round(primary_prob, 4),
                "meta_prob": round(prob, 4),
                "ticket": result.ticket,
                "side": "BUY",
                "entry_price": result.price,
                "tp": tp, "sl": sl,
                "tp_pips": round(tp_pips, 2),
                "sl_pips": round(sl_pips, 2),
                "volume": volume,
                "atr": round(atr_frac, 6),
                "equity_before": equity,
            })

            notify("Trade Placed",
                   f"{symbol} BUY @ {result.price} m={prob:.2f} #{result.ticket}")

        except Exception as e:
            log(f"  ⚠️ Cycle error: {type(e).__name__}: {e}")
        finally:
            try:
                client.sessions.end(aid)
            except Exception:
                pass

    finally:
        if LOCK.exists():
            LOCK.unlink()


if __name__ == "__main__":
    main()
