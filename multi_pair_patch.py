import re

# --- 1. UPDATE trader_config.py ---
p_config = "trader_config.py"
try:
    s_config = open(p_config).read()
    
    # Expand the pairs list (we look for common variable names)
    new_pairs = '["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]'
    
    # Try to replace a list that looks like PAIRS = [...]
    if "PAIRS =" in s_config:
        s_config = re.sub(r'PAIRS\s*=\s*\[.*?\]', f'PAIRS = {new_pairs}', s_config, flags=re.DOTALL)
        open(p_config, "w").write(s_config)
        print("✅ Expanded pairs in trader_config.py")
    else:
        print("⚠️ Could not find PAIRS in trader_config.py. You may need to add them manually.")

except FileNotFoundError:
    print("❌ trader_config.py not found.")

# --- 2. UPDATE auto_trader.py (Pip Sizes & Timeframe) ---
p_trader = "auto_trader.py"
s_trader = open(p_trader).read()

# Expand pip sizes (so it knows JPY pairs are 0.01 and others are 0.0001)
old_pips = '{"EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01}'
new_pips = '''{
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "USDJPY": 0.01, 
    "AUDUSD": 0.0001, "USDCAD": 0.0001, "NZDUSD": 0.0001, 
    "EURGBP": 0.0001, "EURJPY": 0.01, "GBPJPY": 0.01
}'''
if old_pips in s_trader:
    s_trader = s_trader.replace(old_pips, new_pips)
    print("✅ Expanded Pip Sizes")
else:
    # Try regex if exact string failed
    s_trader = re.sub(r'pip_sizes\s*=\s*\{[^\}]+\}', f'pip_sizes = {new_pips}', s_trader)
    print("✅ Expanded Pip Sizes (via regex)")

# Change Timeframe to H1
if '"M5"' in s_trader or "'M5'" in s_trader:
    s_trader = s_trader.replace('"M5"', '"H1"').replace("'M5'", "'H1'")
    print("✅ Switched Timeframe to H1 in auto_trader.py")
elif "M5" in s_trader:
    # Catch any other M5 reference
    s_trader = re.sub(r'\bM5\b', 'H1', s_trader)
    print("✅ Switched Timeframe to H1 (via regex)")

open(p_trader, "w").write(s_trader)
print("Multi-Pair Upgrade Complete!")
