"""Central config for autonomous trading."""

# Model
SIGNAL_THRESHOLD = 0.65      # from backtest
SYMBOL = "USDJPYm"
TIMEFRAME = "M5"

# Trade parameters (from backtest winning config)
TP_PIPS = 10.0
SL_PIPS = 2.0
VOLUME = 0.2

# ── Dynamic sizing by confidence ──
DYNAMIC_SIZING = True
LOT_MIN = 0.01             # broker minimum
LOT_MAX = 0.5              # cap to prevent runaway

# ── ATR-based SL/TP ──
USE_ATR_SLTP = True
ATR_TP_MULTIPLIER = 1.5    # TP = current ATR × 1.5
ATR_SL_MULTIPLIER = 0.5    # SL = current ATR × 0.5
MIN_TP_PIPS = 8.0          # never go tighter than 8 pips
MIN_SL_PIPS = 2.0          # never tighter than 2 pips
MAX_TP_PIPS = 25.0         # never wider than 25 pips
MAX_SL_PIPS = 6.0          # never wider than 6 pips

# Risk limits
MAX_POSITIONS = 5
MAX_TRADES_PER_DAY = 100
DAILY_LOSS_LIMIT_PCT = 3.0

# Session filter (UTC hours)
TRADE_HOURS_UTC_START = 0
TRADE_HOURS_UTC_END = 24

# Market conditions
MAX_SPREAD_PIPS = 2.0
MAX_HOLD_MINUTES = 15

# Paths
PIP = 0.01
KILL_FILE = "KILL"
TRADES_CSV = "trades.csv"

# === SAFETY GUARDS (added after overnight loss) ===


# === SAFETY GUARDS ===
BASE_VOLUME = 0.03
MAX_TRADES_PER_SYMBOL_PER_DAY = 3
MAX_TRADES_PER_HOUR = 2
MAX_CONSECUTIVE_LOSSES = 3
