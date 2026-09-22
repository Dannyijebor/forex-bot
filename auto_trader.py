"""
auto_trader.py — Full autonomous signal-to-execution loop.
Runs every 5 min via cron. Places demo trades when model fires.
Multiple safeguards prevent runaway trading.
"""
import os, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from signal_engine_v2 import fetch_all_pairs
from signal_engine_v3 import score_all_symbols, percentile_threshold

SYMBOL_MAP = {"EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm"}
PIP_SIZE = {"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01}
import trader_config as cfg

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from tickerall import Tickerall

load_dotenv(os.path.expanduser("~/Forex_model/.env"))

LOCK = Path(".auto_trader.lock")
LAST_BAR_FILE = Path(".last_traded_bar")


def size_by_confidence(prob, cfg):
    """Scale lot size by model confidence."""
    if not getattr(cfg, "DYNAMIC_SIZING", False):
        return cfg.VOLUME
    base = getattr(cfg, "BASE_VOLUME", 0.1)
    if prob >= 0.80:
        mult = 3.0
    elif prob >= 0.70:
        mult = 2.0
    elif prob >= 0.60:
        mult = 1.5
    else:
        mult = 1.0
    lot = round(base * mult, 2)
    lot = max(getattr(cfg, "LOT_MIN", 0.01), min(lot, getattr(cfg, "LOT_MAX", 0.5)))
    return lot


def compute_tp_sl(price, atr_frac, pip, cfg):
    """Return (tp, sl) prices using ATR-based sizing."""
    if not getattr(cfg, "USE_ATR_SLTP", False):
        tp = round(price + cfg.TP_PIPS * pip, 5)
        sl = round(price - cfg.SL_PIPS * pip, 5)
        return tp, sl

    # ATR fraction × price = ATR in price terms
    atr_price = atr_frac * price
    atr_pips = atr_price / pip

    tp_pips = max(cfg.MIN_TP_PIPS,
                  min(atr_pips * cfg.ATR_TP_MULTIPLIER, cfg.MAX_TP_PIPS))
    sl_pips = max(cfg.MIN_SL_PIPS,
                  min(atr_pips * cfg.ATR_SL_MULTIPLIER, cfg.MAX_SL_PIPS))

    tp = round(price + tp_pips * pip, 5)
    sl = round(price - sl_pips * pip, 5)
    return tp, sl, tp_pips, sl_pips


def log(msg):
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    try:
        with open("auto_trader.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


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

        # 1. Score all symbols
        pairs = fetch_all_pairs(days=7)
        if any(p is None for p in pairs):
            log("Data fetch failed.")
            return
        results = score_all_symbols(pairs, models_dir="models")
        if not results:
            log("Scoring failed for all symbols.")
            return

        # Apply percentile threshold per symbol
        qualified = []
        for r in results:
            should_fire, dyn_thresh = percentile_threshold(
                f"models/{r['symbol'].lower()}",
                r["prob"],
                lookback=500, percentile=95, min_floor=0.40,
            )
            r["dyn_thresh"] = dyn_thresh
            r["qualified"] = should_fire
            mark = "✓" if should_fire else "✗"
            log(f"  {r['symbol']}: Prob={r['prob']:.4f}  "
                f"PctThresh={dyn_thresh:.4f}  {mark}")

        qualified = [r for r in results if r["qualified"]]
        if not qualified:
            log("  No symbol passed percentile threshold.")
            return

        best = max(qualified, key=lambda r: r["prob"])
        symbol = best["symbol"]
        prob = best["prob"]
        price = best["close"]
        bar_ts = best["timestamp"]
        log(f"  Best: {symbol} @ Prob={prob:.4f}  Close={price:.5f}")

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

            # 9. Signal threshold — handled by percentile_threshold above

            # 10. Spread filter
            tickerall_symbol = SYMBOL_MAP.get(symbol, symbol + "m")
            candles = client.candles.get(aid, symbol=tickerall_symbol, count=1, timeframe=cfg.TIMEFRAME)
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
            pip = PIP_SIZE.get(symbol, 0.01)

            # Dynamic lot size
            volume = size_by_confidence(prob, cfg)

            # Safety: cap risk at 5% of equity per trade
            equity_now = acct.account.equity if hasattr(acct, 'account') else 100.0
            max_risk_usd = equity_now * 0.05
            sl_pips_for_risk = max(cfg.MIN_SL_PIPS, 2.0)
            max_lots = max_risk_usd / (sl_pips_for_risk * 10.0)  # approx $10/pip per lot
            volume = round(min(volume, max_lots), 2)
            volume = max(volume, cfg.LOT_MIN)

            # ATR-based TP/SL
            atr_frac = best.get("atr", 0.001)
            tp, sl, tp_pips, sl_pips = compute_tp_sl(live_price, atr_frac, pip, cfg)

            log(f"  🎯 SIGNAL ({symbol} prob {prob:.3f}) — BUY @ {live_price}")
            log(f"      Volume={volume}  TP={tp} ({tp_pips:.1f}p)  SL={sl} ({sl_pips:.1f}p)")

            try:
                result = client.orders.place(
                    aid, type="market", symbol=tickerall_symbol, side="BUY",
                    volume=volume, stop_loss=sl, take_profit=tp,
                    comment=f"{symbol}-p{prob:.2f}",
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
                "symbol": symbol,
                "prob": round(prob, 4),
                "ticket": result.ticket,
                "side": "BUY",
                "entry_price": result.price,
                "tp": tp,
                "sl": sl,
                "tp_pips": round(tp_pips, 2),
                "sl_pips": round(sl_pips, 2),
                "volume": volume,
                "atr": round(atr_frac, 6),
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
