"""
Forex Bot Dashboard — investor-grade UI.
Dark theme, live indicators, quant-fund style metrics.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timezone, timedelta
import requests
from io import StringIO

# ============================================================
# PAGE CONFIG
# ============================================================
st.set_page_config(
    page_title="Forex Bot · Live Trading",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ============================================================
# CUSTOM CSS — dark, minimal, quant-fund aesthetic
# ============================================================
st.markdown("""
<style>
    /* Base */
    .stApp {
        background: #0a0b0f;
    }
    .main .block-container {
        padding-top: 1.5rem;
        padding-bottom: 3rem;
        max-width: 1400px;
    }
    /* Typography */
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #e8eaed;
    }
    h1, h2, h3 {
        color: #ffffff;
        font-weight: 600;
        letter-spacing: -0.02em;
    }
    /* Hide Streamlit chrome */
    #MainMenu, footer, header {visibility: hidden;}
    /* Metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #131520 0%, #0f1018 100%);
        border: 1px solid #1f2230;
        border-radius: 12px;
        padding: 20px 22px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.3);
    }
    [data-testid="stMetricLabel"] {
        color: #8b91a8 !important;
        font-size: 0.75rem !important;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    [data-testid="stMetricValue"] {
        color: #ffffff !important;
        font-size: 1.75rem !important;
        font-weight: 600;
        letter-spacing: -0.02em;
    }
    [data-testid="stMetricDelta"] {
        font-size: 0.85rem !important;
    }
    /* Custom card */
    .hero-card {
        background: linear-gradient(135deg, #1a1e2e 0%, #0f1118 100%);
        border: 1px solid #252a3d;
        border-radius: 16px;
        padding: 28px 32px;
        margin-bottom: 24px;
        position: relative;
        overflow: hidden;
    }
    .hero-card::before {
        content: '';
        position: absolute;
        top: 0; left: 0; right: 0;
        height: 2px;
        background: linear-gradient(90deg, #3b82f6 0%, #8b5cf6 50%, #ec4899 100%);
    }
    .hero-title {
        font-size: 1.9rem;
        font-weight: 700;
        color: #ffffff;
        letter-spacing: -0.03em;
        margin: 0 0 8px 0;
    }
    .hero-subtitle {
        color: #8b91a8;
        font-size: 0.95rem;
        margin: 0;
    }
    .status-dot {
        display: inline-block;
        width: 8px; height: 8px;
        border-radius: 50%;
        margin-right: 8px;
        vertical-align: middle;
    }
    .status-live { background: #10b981; box-shadow: 0 0 12px #10b981; animation: pulse 2s infinite; }
    .status-idle { background: #f59e0b; }
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
    }
    .badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 6px;
        font-size: 0.75rem;
        font-weight: 600;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-right: 8px;
    }
    .badge-live { background: rgba(16,185,129,0.15); color: #10b981; border: 1px solid rgba(16,185,129,0.3); }
    .badge-demo { background: rgba(59,130,246,0.15); color: #3b82f6; border: 1px solid rgba(59,130,246,0.3); }
    .badge-symbol { background: rgba(139,92,246,0.15); color: #a78bfa; border: 1px solid rgba(139,92,246,0.3); }
    /* Section headers */
    .section-title {
        font-size: 0.8rem;
        font-weight: 600;
        color: #8b91a8;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        margin: 32px 0 16px 0;
        padding-bottom: 8px;
        border-bottom: 1px solid #1f2230;
    }
    /* Empty state */
    .empty-state {
        background: linear-gradient(135deg, #131520 0%, #0f1018 100%);
        border: 1px dashed #2a2f42;
        border-radius: 16px;
        padding: 48px 32px;
        text-align: center;
        margin: 24px 0;
    }
    .empty-icon {
        font-size: 3rem;
        margin-bottom: 12px;
        opacity: 0.5;
    }
    .empty-title {
        font-size: 1.2rem;
        font-weight: 600;
        color: #ffffff;
        margin-bottom: 8px;
    }
    .empty-text {
        color: #8b91a8;
        font-size: 0.9rem;
        max-width: 500px;
        margin: 0 auto;
        line-height: 1.6;
    }
    /* Dataframe */
    [data-testid="stDataFrame"] {
        background: #0f1018;
        border-radius: 12px;
        border: 1px solid #1f2230;
    }
    /* Buttons / links */
    a { color: #3b82f6 !important; text-decoration: none; }
    a:hover { color: #60a5fa !important; text-decoration: underline; }
    /* Divider */
    hr { border-color: #1f2230; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# CONFIG
# ============================================================
REPO = "Dannyijebor/forex-bot"
BRANCH = "main"
TRADES_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/trades.csv"
CONFIG_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/trader_config.py"


# ============================================================
# DATA LOADERS
# ============================================================
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
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300)
def load_config():
    try:
        r = requests.get(CONFIG_URL, timeout=10)
        r.raise_for_status()
        cfg = {}
        for line in r.text.splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                cfg[k.strip()] = v.split("#")[0].strip()
        return cfg
    except Exception:
        return {}


# ============================================================
# HELPERS
# ============================================================
def compute_metrics(df):
    """Compute investor-grade metrics."""
    if df.empty or "pnl_usd" not in df.columns:
        return {}
    completed = df.dropna(subset=["pnl_usd"])
    if len(completed) == 0:
        return {}

    pnl = completed["pnl_usd"].astype(float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl <= 0]

    total_pnl = pnl.sum()
    win_rate = len(wins) / len(pnl) * 100 if len(pnl) else 0
    avg_win = wins.mean() if len(wins) else 0
    avg_loss = losses.mean() if len(losses) else 0
    profit_factor = abs(wins.sum() / losses.sum()) if len(losses) and losses.sum() != 0 else float('inf')

    # Equity curve
    equity = pnl.sort_index().cumsum()
    peak = equity.cummax()
    drawdown = equity - peak
    max_dd = drawdown.min()

    # Sharpe (per-trade, annualized ~250 trading days × ~10 trades/day)
    if pnl.std() > 0:
        sharpe = pnl.mean() / pnl.std() * np.sqrt(250 * 10)
    else:
        sharpe = 0

    # Sortino (downside deviation only)
    downside = pnl[pnl < 0]
    if len(downside) > 0 and downside.std() > 0:
        sortino = pnl.mean() / downside.std() * np.sqrt(250 * 10)
    else:
        sortino = 0

    return {
        "total_trades": len(pnl),
        "total_pnl": total_pnl,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "max_dd": max_dd,
        "sharpe": sharpe,
        "sortino": sortino,
        "avg_trade": pnl.mean(),
    }


def make_equity_curve(df):
    """Dark-themed cumulative equity chart."""
    if df.empty or "pnl_usd" not in df.columns:
        return None
    df_s = df.sort_values("opened_utc").copy()
    df_s["equity"] = df_s["pnl_usd"].astype(float).cumsum()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_s["opened_utc"], y=df_s["equity"],
        mode="lines",
        line=dict(color="#3b82f6", width=2.5, shape="spline"),
        fill="tozeroy",
        fillcolor="rgba(59,130,246,0.08)",
        hovertemplate="<b>%{x|%b %d %H:%M}</b><br>P&L: $%{y:.2f}<extra></extra>",
        name="Cumulative P&L",
    ))
    fig.update_layout(
        height=320,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8b91a8", family="Inter", size=11),
        xaxis=dict(gridcolor="#1a1d28", showline=False, zeroline=False),
        yaxis=dict(gridcolor="#1a1d28", showline=False, zeroline=False,
                   tickprefix="$", tickformat=".2f"),
        hovermode="x unified",
        showlegend=False,
    )
    return fig


def make_drawdown_chart(df):
    """Underwater curve."""
    if df.empty or "pnl_usd" not in df.columns:
        return None
    df_s = df.sort_values("opened_utc").copy()
    df_s["equity"] = df_s["pnl_usd"].astype(float).cumsum()
    df_s["peak"] = df_s["equity"].cummax()
    df_s["dd"] = (df_s["equity"] - df_s["peak"]).clip(upper=0)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_s["opened_utc"], y=df_s["dd"],
        mode="lines",
        line=dict(color="#ef4444", width=1.8),
        fill="tozeroy",
        fillcolor="rgba(239,68,68,0.12)",
        hovertemplate="<b>%{x|%b %d %H:%M}</b><br>Drawdown: $%{y:.2f}<extra></extra>",
        name="Drawdown",
    ))
    fig.update_layout(
        height=180,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8b91a8", family="Inter", size=11),
        xaxis=dict(gridcolor="#1a1d28", showline=False),
        yaxis=dict(gridcolor="#1a1d28", showline=False,
                   tickprefix="$", tickformat=".2f"),
        showlegend=False,
    )
    return fig


def make_prob_histogram(df):
    """Signal probability distribution."""
    if df.empty or "prob" not in df.columns:
        return None
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=df["prob"],
        nbinsx=20,
        marker=dict(color="#8b5cf6", line=dict(color="#1a1d28", width=1)),
        opacity=0.85,
        hovertemplate="Prob %{x:.2f}<br>Count: %{y}<extra></extra>",
    ))
    fig.update_layout(
        height=220,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#8b91a8", family="Inter", size=11),
        xaxis=dict(gridcolor="#1a1d28", title="", showline=False),
        yaxis=dict(gridcolor="#1a1d28", title="", showline=False),
        showlegend=False,
        bargap=0.05,
    )
    return fig


# ============================================================
# HERO HEADER
# ============================================================
cfg = load_config()
threshold = cfg.get("SIGNAL_THRESHOLD", "0.65")

st.markdown(f"""
<div class="hero-card">
    <div class="hero-title">◆ Forex Bot</div>
    <div class="hero-subtitle">
        <span class="status-dot status-live"></span>Live · 
        Multi-symbol ML ensemble · EUR/USD + GBP/USD · 
        {datetime.now(timezone.utc).strftime('%H:%M UTC')}
    </div>
    <div style="margin-top: 16px;">
        <span class="badge badge-live">● Running</span>
        <span class="badge badge-demo">Demo Account</span>
        <span class="badge badge-symbol">Threshold {threshold}</span>
    </div>
</div>
""", unsafe_allow_html=True)


# ============================================================
# LOAD DATA
# ============================================================
df = load_trades()
metrics = compute_metrics(df)


# ============================================================
# EMPTY STATE
# ============================================================
if df.empty or len(df) < 1:
    st.markdown("""
    <div class="empty-state">
        <div class="empty-icon">◇</div>
        <div class="empty-title">Awaiting first signal</div>
        <div class="empty-text">
            The model evaluates every 5 minutes and fires only on high-conviction bars.
            Expect 10–30 trades per day across EUR/USD and GBP/USD.
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown('<div class="section-title">System Architecture</div>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Signal Threshold", threshold)
    c2.metric("Max Concurrent", cfg.get("MAX_POSITIONS", "5"))
    c3.metric("Max Hold (min)", cfg.get("MAX_HOLD_MINUTES", "15"))
    c4.metric("Symbols", "2")

    st.markdown('<div class="section-title">How It Works</div>', unsafe_allow_html=True)
    st.markdown("""
    - **Data Layer** — Dukascopy M5 bars for USD/JPY, EUR/USD, GBP/USD  
    - **Model Layer** — 42 engineered features, ensemble of HGB + RandomForest + LightGBM  
    - **Signal Layer** — Best-of-N selection on cross-validated AUC 0.64–0.67  
    - **Execution Layer** — TickerAll → Exness demo · 10-pip TP · 2-pip SL · 15-min max hold  
    - **Orchestration** — GitHub Actions every 5 min via external cron trigger  
    """)

    st.markdown("""
    <div style="text-align: center; margin-top: 48px; color: #4b5163; font-size: 0.8rem;">
        Dashboard refreshes every 60 seconds · Data from GitHub repo
    </div>
    """, unsafe_allow_html=True)
    st.stop()


# ============================================================
# KEY METRICS ROW
# ============================================================
st.markdown('<div class="section-title">Performance Overview</div>', unsafe_allow_html=True)

m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total Trades", f"{metrics['total_trades']:,}")
m2.metric("Win Rate", f"{metrics['win_rate']:.1f}%")
m3.metric("Net P&L",
          f"${metrics['total_pnl']:+.2f}",
          delta=f"${metrics['avg_trade']:+.3f}/trade")
m4.metric("Profit Factor",
          f"{metrics['profit_factor']:.2f}" if metrics['profit_factor'] != float('inf') else "∞")
m5.metric("Sharpe",
          f"{metrics['sharpe']:.2f}")


# ============================================================
# RISK METRICS ROW
# ============================================================
st.markdown('<div class="section-title">Risk & Quality</div>', unsafe_allow_html=True)

r1, r2, r3, r4 = st.columns(4)
r1.metric("Max Drawdown", f"${metrics['max_dd']:.2f}")
r2.metric("Avg Win", f"${metrics['avg_win']:+.2f}")
r3.metric("Avg Loss", f"${metrics['avg_loss']:+.2f}")
r4.metric("Sortino", f"{metrics['sortino']:.2f}")


# ============================================================
# EQUITY CURVE
# ============================================================
st.markdown('<div class="section-title">Equity Curve</div>', unsafe_allow_html=True)
eq_fig = make_equity_curve(df)
if eq_fig:
    st.plotly_chart(eq_fig, use_container_width=True, config={"displayModeBar": False})


# ============================================================
# DRAWDOWN
# ============================================================
st.markdown('<div class="section-title">Underwater (Drawdown)</div>', unsafe_allow_html=True)
dd_fig = make_drawdown_chart(df)
if dd_fig:
    st.plotly_chart(dd_fig, use_container_width=True, config={"displayModeBar": False})


# ============================================================
# PER-SYMBOL
# ============================================================
if "symbol" in df.columns and df["symbol"].nunique() >= 1:
    st.markdown('<div class="section-title">Per-Symbol Breakdown</div>', unsafe_allow_html=True)

    symbol_stats = []
    for sym in df["symbol"].dropna().unique():
        sub = df[df["symbol"] == sym].dropna(subset=["pnl_usd"])
        if len(sub) == 0:
            continue
        pnl = sub["pnl_usd"].astype(float)
        symbol_stats.append({
            "Symbol": sym,
            "Trades": len(sub),
            "Win Rate": f"{(pnl > 0).mean()*100:.1f}%",
            "Net P&L": f"${pnl.sum():+.2f}",
            "Avg": f"${pnl.mean():+.3f}",
            "Best": f"${pnl.max():+.2f}",
            "Worst": f"${pnl.min():+.2f}",
        })
    if symbol_stats:
        st.dataframe(pd.DataFrame(symbol_stats), use_container_width=True, hide_index=True)


# ============================================================
# SIGNAL DISTRIBUTION
# ============================================================
if "prob" in df.columns:
    st.markdown('<div class="section-title">Signal Confidence Distribution</div>', unsafe_allow_html=True)
    prob_fig = make_prob_histogram(df)
    if prob_fig:
        st.plotly_chart(prob_fig, use_container_width=True, config={"displayModeBar": False})


# ============================================================
# RECENT TRADES
# ============================================================
st.markdown('<div class="section-title">Recent Trades</div>', unsafe_allow_html=True)

display_cols = [c for c in ["opened_utc", "symbol", "side", "volume",
                              "entry_price", "tp", "sl", "prob", "pnl_usd", "status"]
                if c in df.columns]
recent = df[display_cols].head(30).copy()
if "opened_utc" in recent.columns:
    recent["opened_utc"] = recent["opened_utc"].dt.strftime("%b %d %H:%M")

st.dataframe(recent, use_container_width=True, hide_index=True, height=400)


# ============================================================
# FOOTER
# ============================================================
st.markdown("---")
st.markdown(f"""
<div style="text-align: center; color: #4b5163; font-size: 0.8rem; padding: 20px 0;">
    Data as of {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC ·
    Refreshes every 60s · Demo account only, no real money at risk
</div>
""", unsafe_allow_html=True)
