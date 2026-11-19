import re

# --- 1. UPDATE signal_engine_v5.py (Pairs List) ---
p_sig = "signal_engine_v5.py"
s_sig = open(p_sig).read()

new_symbols = '''TICKERALL_SYMBOLS = {
    "EURUSD": "EURUSDm", "GBPUSD": "GBPUSDm", "USDJPY": "USDJPYm",
    "AUDUSD": "AUDUSDm", "USDCAD": "USDCADm", "NZDUSD": "NZDUSDm",
    "EURGBP": "EURGBPm", "EURJPY": "EURJPYm", "GBPJPY": "GBPJPYm"
}'''

# Replace the existing dictionary
s_sig = re.sub(r'TICKERALL_SYMBOLS\s*=\s*\{.*?\}', new_symbols, s_sig, flags=re.DOTALL)
open(p_sig, "w").write(s_sig)
print("✅ Expanded pairs in signal_engine_v5.py")

# --- 2. UPDATE auto_trader.py (Lookahead for H1) ---
p_trader = "auto_trader.py"
s_trader = open(p_trader).read()

# Change lookahead from 15 mins to 240 mins (4 H1 bars)
old_lookahead = 'def label_signals(pairs, lookahead_min=15, pip_sizes=None):'
new_lookahead = 'def label_signals(pairs, lookahead_min=240, pip_sizes=None): # 4 H1 bars'

if old_lookahead in s_trader:
    s_trader = s_trader.replace(old_lookahead, new_lookahead)
    print("✅ Updated lookahead to 4 hours (240 mins)")
else:
    print("⚠️ Could not find lookahead_min=15")

open(p_trader, "w").write(s_trader)
print("Done!")
