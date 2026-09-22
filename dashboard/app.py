"""
Streamlit dashboard for forex-bot trading activity.
Reads trades.csv and daemon.log from the public GitHub repo.
"""
import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timezone, timedelta
import requests
from io import StringIO

st.set_page_config(page_title="Forex Bot", page_icon="📈", layout="wide")

REPO = "Dannyijebor/forex-bot"
BRANCH = "main"
TRADES_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/trades.csv"

st.title("📈 Forex Bot Dashboard")
st.caption(f"Bot runs on GitHub Actions · Auto-refresh every 5 min")
st.caption(f"Last page load: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC")


@st.cache_data(ttl=60)
def load_trades():
    try:
        r = requests.get(TRADES_URL, timeout=10)
        r.raise_for_status()
        if not r.text.strip():
            return pd.DataFrame()
        df = pd.read_csv(StringIO(r.text))
        if "opened_utc" in df.columns:
            df["opened_utc"] = pd.to_datetime(df["opened_utc"], format="mixed", utc=True)
            df = df.sort_values("opened_utc", ascending=False)
        return df
    except Exception as e:
        st.error(f"Failed to load trades: {e}")
        return pd.DataFrame()


df = load_trades()

if df.empty:
    st.info("🎯 No trades yet. The bot fires when model confidence ≥ 0.75. This is rare — expect 0–3 trades per day.")
    st.markdown("### What's happening")
    st.markdown("- GitHub Actions runs the trading cycle every 5 minutes")
    st.markdown("- Model scores each bar and fires when prob ≥ 0.75")
    st.markdown("- When it fires, a demo trade is placed on Exness")
    st.markdown("- Check back in a few hours")
    st.stop()

# ── Top metrics ──
c1, c2, c3, c4 = st.columns(4)

total_trades = len(df)
wins = df[df["pnl_usd"] > 0] if "pnl_usd" in df.columns else df.iloc[0:0]
losses = df[df["pnl_usd"] <= 0] if "pnl_usd" in df.columns else df.iloc[0:0]

c1.metric("Total trades", f"{total_trades}")

if len(df) > 0 and "pnl_usd" in df.columns:
    win_rate = len(wins) / total_trades * 100
    total_pnl = df["pnl_usd"].sum()
    avg_win = wins["pnl_usd"].mean() if len(wins) else 0
    avg_loss = losses["pnl_usd"].mean() if len(losses) else 0

    c2.metric("Win rate", f"{win_rate:.1f}%")
    c3.metric("Total P&L", f"${total_pnl:+.2f}",
              delta=f"${total_pnl/total_trades:+.3f}/trade" if total_trades else "0")
    c4.metric("Avg win / loss", f"${avg_win:+.2f} / ${avg_loss:.2f}")

# ── Equity curve ──
if "pnl_usd" in df.columns and len(df) > 1:
    df_sorted = df.sort_values("opened_utc")
    df_sorted["cumulative_pnl"] = df_sorted["pnl_usd"].cumsum()
    fig = px.line(df_sorted, x="opened_utc", y="cumulative_pnl",
                  title="Cumulative P&L ($)", markers=True)
    fig.update_layout(height=350, margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig, use_container_width=True)

# ── Probability distribution ──
if "prob" in df.columns:
    fig2 = px.histogram(df, x="prob", nbins=20, title="Signal probability distribution")
    fig2.update_layout(height=280, margin=dict(l=0, r=0, t=40, b=0))
    st.plotly_chart(fig2, use_container_width=True)

# ── Recent trades table ──
st.subheader("📋 Recent trades")
cols_to_show = [c for c in ["opened_utc", "symbol", "side", "volume",
                             "entry_price", "tp", "sl", "prob", "pnl_usd", "status"]
                if c in df.columns]
st.dataframe(df[cols_to_show].head(50), use_container_width=True, hide_index=True)

# ── Footer ──
st.markdown("---")
st.caption("Dashboard refreshes automatically. Trades come from GitHub Actions runs.")
st.caption("⚠️ Demo account only — no real money at risk.")
