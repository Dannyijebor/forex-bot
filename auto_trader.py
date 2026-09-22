"""
auto_trader.py — Full autonomous signal-to-execution loop.
Runs every 5 min via cron. Places demo trades when model fires.
Multiple safeguards prevent runaway trading.
"""
import os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine import load_artifacts, compute_features, predict_proba
import trader_config as cfg

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from tickerall import Tickerall

load_dotenv(os.path.expanduser("~/Forex_model/.env"))

LOCK = Path(".auto_trader.lock")
LAST_BAR_FILE = Path(".last_traded_bar")


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)


def notify(title, content):
    # Termux-only notifications. GitHub Actions just prints.
    if os.path.exists("/data/data/com.termux/files/usr/bin/termux-notification"):
        os.system(f'termux-notification --title "{title}" --content "{content}" --priority high')
    else:
        print(f"[NOTIFY] {title}: {content}")


def kill_switch_active():
    return Path(cfg.KILL_FILE).exists()


def fetch_bars():
    import dukascopy_python as dp
    from dukascopy_python.instruments import INSTRUMENT_FX_MAJORS_USD_JPY
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    start = end - timedelta(days=7)
    df = dp.fetch(
        instrument=INSTRUMENT_FX_MAJORS_USD_JPY,
        interval=dp.INTERVAL_MIN_5, offer_side=dp.OFFER_SIDE_BID,
        start=start, end=end, max_retries=3,
    )
    return df.sort_index() if df is not None and len(df) else None


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


def main():
    # Lock to prevent overlap
    if LOCK.exists():
        age = time.time() - LOCK.stat().st_mtime
        if age < 240:
            log(f"Locked ({age:.0f}s). Exiting.")
            return
    LOCK.touch()

    try:
        if kill_switch_active():
            log("KILL switch active — no trading. Remove KILL file to resume.")
            return

        # 1. Score current bar
        model, mean, scale, features = load_artifacts("models")
        bars = fetch_bars()
        if bars is None:
            log("Data fetch failed.")
            return
        df = bars.copy()
        df.columns = [c.capitalize() for c in df.columns]
        df = compute_features(df).dropna(subset=features)
        if len(df) < 2:
            log("Insufficient bars.")
            return

        x = df[features].iloc[-1].to_numpy(dtype=np.float64)
        prob = predict_proba(model, (x - mean) / scale)
        bar_ts = df.index[-1]
        price = float(df["Close"].iloc[-1])
        log(f"Bar {bar_ts}  Close {price:.3f}  Prob {prob:.4f}")

        # 2. Connect to broker (with retry for network blips)
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
                log(f"  Session start attempt {attempt+1}/3 failed: {e}")
                time.sleep(5)
        if session is None:
            log("  All session start attempts failed. Exiting cycle.")
            return

        # HARD SAFETY: refuse live accounts
        if not session.is_demo:
            log("❌ LIVE ACCOUNT DETECTED — refusing to trade.")
            notify("BLOCKED", "Attempted trade on LIVE account — aborted.")
            client.sessions.end(session.account_id)
            return

        aid = session.account_id

        try:
            # 3. Get current state
            acct = client.accounts.get(aid)
            equity = acct.account.equity
            balance = acct.account.balance
            open_positions = acct.positions or []
            log(f"  Equity ${equity:.2f}  Positions {len(open_positions)}")

            # 4. Session filter
            if not in_trading_window():
                log(f"  Outside trade window ({cfg.TRADE_HOURS_UTC_START}-{cfg.TRADE_HOURS_UTC_END} UTC).")
                return

            # 5. Manage existing positions — profit-based time exit
            for p in open_positions:
                open_time = getattr(p, "open_time", None)
                if open_time:
                    try:
                        ot = datetime.fromisoformat(open_time.replace("Z", "+00:00"))
                        age_min = (datetime.now(timezone.utc) - ot).total_seconds() / 60
                        if age_min > cfg.MAX_HOLD_MINUTES:
                            profit = getattr(p, "profit", 0) or 0
                            if profit > 0:
                                log(f"  Position {p.ticket} age {age_min:.0f}min, profit ${profit:+.2f} — closing (time-profit exit).")
                                close_position(client, aid, p.ticket, "time_profit")
                            else:
                                log(f"  Position {p.ticket} age {age_min:.0f}min, profit ${profit:+.2f} — holding to SL/TP.")
                    except Exception as e:
                        log(f"  Hold check error: {e}")

            # Re-fetch after possible closes
            acct = client.accounts.get(aid)
            open_positions = acct.positions or []
            equity = acct.account.equity

            # 6. Position limit
            if len(open_positions) >= cfg.MAX_POSITIONS:
                log(f"  At max positions ({cfg.MAX_POSITIONS}). Skipping entry.")
                return

            # 7. Daily loss limit
            today_trades = load_todays_trades()
            if len(today_trades) > 0 and "pnl_usd" in today_trades.columns:
                daily_pnl = today_trades["pnl_usd"].fillna(0).sum()
                loss_pct = -daily_pnl / balance * 100
                if loss_pct >= cfg.DAILY_LOSS_LIMIT_PCT:
                    log(f"  Daily loss limit hit ({loss_pct:.2f}%). No more trades today.")
                    notify("Daily Limit", f"Loss {loss_pct:.1f}% — trading paused today")
                    return

            # 8. Daily trade count
            if len(today_trades) >= cfg.MAX_TRADES_PER_DAY:
                log(f"  At daily trade cap ({cfg.MAX_TRADES_PER_DAY}).")
                return

            # 9. Signal threshold
            if prob < cfg.SIGNAL_THRESHOLD:
                log(f"  No signal (prob {prob:.4f} < {cfg.SIGNAL_THRESHOLD}).")
                return

            # 10. Spread filter
            candles = client.candles.get(aid, symbol=cfg.SYMBOL, count=1, timeframe=cfg.TIMEFRAME)
            c = candles[-1]
            spread_pips = (c.close - c.bid) / cfg.PIP if c.bid else 0
            # TickerAll shows spread=0.0 often — use bid vs ask if available
            live_price = c.bid if c.bid else c.close
            if spread_pips > cfg.MAX_SPREAD_PIPS:
                log(f"  Spread {spread_pips:.2f} pips > limit. Skipping.")
                return

            # 10.5. Already-traded-this-bar check
            bar_key = str(bar_ts)
            if LAST_BAR_FILE.exists() and LAST_BAR_FILE.read_text().strip() == bar_key:
                log(f"  Already traded bar {bar_key}. Skipping.")
                return

            # 11. Place order
            tp = round(live_price + cfg.TP_PIPS * cfg.PIP, 3)
            sl = round(live_price - cfg.SL_PIPS * cfg.PIP, 3)
            log(f"  🎯 SIGNAL FIRED (prob {prob:.3f}) — placing BUY @ {live_price} TP={tp} SL={sl}")

            try:
                result = client.orders.place(
                    aid, type="market", symbol=cfg.SYMBOL, side="BUY",
                    volume=cfg.VOLUME, stop_loss=sl, take_profit=tp,
                    comment=f"auto-p{prob:.2f}",
                    timeout=90.0,
                )
            except Exception as oe:
                log(f"  Order placement failed: {type(oe).__name__}: {oe}")
                return
            LAST_BAR_FILE.write_text(bar_key)
            log(f"  Order placed: ticket={result.ticket} status={result.status} price={result.price}")

            log_trade({
                "opened_utc": datetime.now(timezone.utc).isoformat(),
                "bar_utc": bar_ts.isoformat() if hasattr(bar_ts, "isoformat") else str(bar_ts),
                "prob": round(prob, 4),
                "ticket": result.ticket,
                "side": "BUY",
                "entry_price": result.price,
                "tp": tp,
                "sl": sl,
                "volume": cfg.VOLUME,
                "equity_before": equity,
            })

            notify("Trade Placed",
                   f"BUY {cfg.SYMBOL} @ {result.price:.3f}  P={prob:.2f}  #{result.ticket}")

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
