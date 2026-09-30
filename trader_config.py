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
MIN_TP_PIPS = 15.0         # broker requires min 10+ pips
MIN_SL_PIPS = 10.0         # broker requires min 10 pips
MAX_TP_PIPS = 30.0         # 30 pips max
MAX_SL_PIPS = 15.0         # 15 pips max

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
BASE_VOLUME = 0.21
MAX_TRADES_PER_SYMBOL_PER_DAY = 15
MAX_TRADES_PER_HOUR = 2
MAX_CONSECUTIVE_LOSSES = 2

# === EXIT RULES (added 2026-09-23) ===
COLLECTIVE_TP_USD = 50.0      # collective take-profit

# === EXIT + ADAPTIVE RULES (2026-09-23) ===
COLLECTIVE_TP_USD = 50.0      # collective take-profit

# === EXIT RULES (2026-09-23 v2) ===
COLLECTIVE_TP_USD = 50.0      # collective take-profit
PROFIT_TAKE_USD = 15.00        # close any profitable trade at $2
PROFIT_HOLD_MINUTES = 5       # ...after 2 minutes open minimum

# === ADAPTIVE SCOREBOARD ===
ADAPTIVE_WINDOW = 5           # look at last N closed trades
ADAPTIVE_LOOSEN_THRESHOLD = 0.60   # if win rate >= 60%, loosen by step
ADAPTIVE_TIGHTEN_THRESHOLD = 0.40  # if win rate <= 40%, tighten by step
ADAPTIVE_STEP = 0.02          # how much to move per cycle
ADAPTIVE_MIN_PRIMARY = 0.35   # hard floor
ADAPTIVE_MAX_PRIMARY = 0.50   # hard ceiling

# === SESSION-AWARE SCALING ===
SESSION_SCALING_ENABLED = True

# === BLOCKED TRADING WINDOWS (UTC, hour ranges [start, end)) ===
# Post exit-v2 analysis (2026-09-30):
#   19-21 UTC: NY close, thin liquidity, net -$19.61
#   05-07 UTC: pre-London chop, net -$38.84 (3x USDJPY BUY SL sweeps)
BLOCKED_HOURS_UTC = [
    (19, 22),   # 8pm-11pm WAT
    (5, 8),     # 6am-9am WAT
]


def session_profile(now_utc):
    """Return (name, sym_mult, hourly_cap, active) for given UTC datetime.

    Windows (UTC):
      Sydney 21:00-00:00 -> thin, 0.3x
      Tokyo  00:00-07:00 -> moderate, 0.6x
      London 07:00-12:00 -> rising, 1.0x
      Overlap 12:00-16:00 -> peak liquidity, 1.7x  <- best signals
      NY     16:00-21:00 -> fading, 0.8x
      Weekend Fri 21:00 - Sun 21:00 -> closed
    """
    wd = now_utc.weekday()   # Mon=0 .. Sun=6
    h = now_utc.hour
    # Weekend: Fri 21:00 UTC -> Sun 21:00 UTC
    if wd == 4 and h >= 21:
        return ("weekend", 0.0, 0, False)
    if wd == 5:
        return ("weekend", 0.0, 0, False)
    if wd == 6 and h < 21:
        return ("weekend", 0.0, 0, False)

    # Blocked hours (skip trading entirely)
    for start_h, end_h in BLOCKED_HOURS_UTC:
        if start_h <= h < end_h:
            return ("blocked", 0.0, 0, False)
    # Session tiers
    if 12 <= h < 16:
        return ("overlap", 1.7, 4, True)
    if 7 <= h < 12:
        return ("london", 1.0, 2, True)
    if 16 <= h < 21:
        return ("ny", 0.8, 2, True)
    if 0 <= h < 7:
        return ("tokyo", 0.6, 1, True)
    return ("sydney", 0.3, 1, True)

# === LOSS-STREAK RECOVERY (decaying confidence penalty) ===
LOSS_STREAK_PENALTY = 0.08            # threshold bump right after 2 losses
LOSS_STREAK_HOLD_MIN = 10             # hold full penalty for this many minutes
LOSS_STREAK_DECAY_HALFLIFE_MIN = 10   # then halve every N minutes
LOSS_STREAK_PENALTY_ZERO = 0.005      # below this, snap to 0
LOSS_STREAK_HARD_BLOCK = 4            # hard pause when streak hits this
LOSS_STREAK_HARD_BLOCK_COOLDOWN_MIN = 30  # ...for this many minutes after last loss

# === EXIT LOGIC v2 (2026-09-29) ===
# Size-aware profit-take: $ target scales with lot size
PROFIT_TAKE_PER_VOLUME = 80.0   # profit_target = max(5, volume * 80)

# Model-aware early exit: close losers when the model flips
MODEL_AWARE_EXIT_ENABLED = True
MODEL_AWARE_EXIT_MIN_AGE_MIN = 2      # don't exit in first N minutes
MODEL_AWARE_EXIT_MAX_LOSS_USD = 8.0   # if loss > this, let SL handle it
MODEL_AWARE_EXIT_META_BUFFER = 0.05   # meta must drop below (threshold - buffer)

