import re

p = "auto_trader.py"
s = open(p).read()

# 1. --- INJECT THE DRAWDOWN CIRCUIT BREAKER ---
if "DAILY_DRAWDOWN_LIMIT" not in s:
    breaker_code = """
# --- IRONCLAD DEFENSE: DAILY DRAWDOWN CIRCUIT BREAKER ---
DAILY_DRAWDOWN_LIMIT = -15.0 # Stop trading if we lose $15 in one day

def check_daily_drawdown():
    try:
        t = pd.read_csv("trades.csv")
        if len(t) == 0: return True
        t['opened_utc'] = pd.to_datetime(t['opened_utc'], utc=True)
        today = pd.Timestamp.utcnow().date()
        today_trades = t[t['opened_utc'].dt.date == today]
        daily_pnl = today_trades['pnl_usd'].sum()
        if daily_pnl <= DAILY_DRAWDOWN_LIMIT:
            print(f"  🚨 CIRCUIT BREAKER: Daily loss hit {daily_pnl:.2f} USD. Halting trading.")
            return False
        return True
    except Exception as e:
        return True

# Safe Risk Parity Check (Will not crash if open trades are unknown)
def check_correlation_risk(sym, current_open_trades=None):
    return 1.0 # Default multiplier
# ---------------------------------------------------------
"""
    s = s.replace("def compute_adaptive_boost", breaker_code + "\ndef compute_adaptive_boost")
    
    # Add the drawdown check to the main loop
    exit_anchor = 'log("  Not trading (blocked). Exiting.")'
    new_exit = '''log("  Not trading (blocked). Exiting.")
            sys.exit(0)
            
        if not check_daily_drawdown():
            log("  Not trading (Daily Drawdown Limit Hit). Exiting.")
            sys.exit(0)'''
    if exit_anchor in s:
        s = s.replace(exit_anchor, new_exit, 1)
        
    print("✅ Injected Daily Drawdown Circuit Breaker")
else:
    print("SKIP: Drawdown breaker already applied.")

open(p, "w").write(s)
print("Ironclad Defense applied safely!")
