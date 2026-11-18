import re

p = "auto_trader.py"
s = open(p).read()

# 1. Upgrade ATR to Swing Trading targets (3x TP, 1.5x SL)
old_atr = '    return max(15.0, atr_pips * 2.0), max(10.0, atr_pips * 1.0)'
new_atr = '''    # SWING MODE: Aim for 3x ATR on TP, 1.5x ATR on SL. 
    # If ATR is small (quiet market), fallback to a minimum of 40 pips TP / 25 pips SL.
    return max(40.0, atr_pips * 3.0), max(25.0, atr_pips * 1.5)'''

if old_atr in s:
    s = s.replace(old_atr, new_atr)
    print("✅ Upgraded TP/SL to Swing Mode (40+ pips)")
else:
    print("⚠️ Could not find ATR return line. It may already be patched.")

# 2. Add Trade Cooldown (60 minutes per pair)
if "TRADE_COOLDOWN_MINUTES" not in s:
    cooldown_code = """
# --- SWING UPGRADE: TRADE COOLDOWN ---
TRADE_COOLDOWN_MINUTES = 60

def is_on_cooldown(symbol):
    try:
        t = pd.read_csv("trades.csv")
        if len(t) == 0: return False
        t['opened_utc'] = pd.to_datetime(t['opened_utc'], utc=True)
        sym_trades = t[t['symbol'] == symbol].sort_values('opened_utc')
        if len(sym_trades) == 0: return False
        
        last_trade_time = sym_trades.iloc[-1]['opened_utc']
        now = pd.Timestamp.utcnow()
        mins_since = (now - last_trade_time).total_seconds() / 60
        
        if mins_since < TRADE_COOLDOWN_MINUTES:
            return True
        return False
    except Exception:
        return False
# -------------------------------------
"""
    s = s.replace("def compute_adaptive_boost", cooldown_code + "\ndef compute_adaptive_boost")
    
    # Inject the cooldown check into the main loop
    anchor = '        side = apply_contrarian_logic(sym, side)'
    cooldown_inject = '''        side = apply_contrarian_logic(sym, side)
        
        # --- SWING UPGRADE: COOLDOWN CHECK ---
        if is_on_cooldown(sym):
            print(f"  {sym} is on a 60-minute cooldown. Skipping.")
            continue
        # -------------------------------------'''
    
    if anchor in s:
        s = s.replace(anchor, cooldown_inject)
        print("✅ Injected Trade Cooldown")
    else:
        print("⚠️ Could not find anchor for cooldown.")
else:
    print("SKIP: Cooldown already exists.")

open(p, "w").write(s)
print("Swing Patch applied!")
