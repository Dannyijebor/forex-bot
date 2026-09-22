"""Central config for autonomous trading."""

# Model
SIGNAL_THRESHOLD = 0.65      # from backtest
SYMBOL = "USDJPYm"
TIMEFRAME = "M5"

# Trade parameters (from backtest winning config)
TP_PIPS = 10.0
SL_PIPS = 2.0
VOLUME = 0.2

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
