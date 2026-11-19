import re

p = "signal_engine_v5.py"
s = open(p).read()

# 1. Fix the fetch_all_pairs_live hardcoded list
s = s.replace('for sym in ["USDJPY", "EURUSD", "GBPUSD"]', 'for sym in TICKERALL_SYMBOLS.keys()')

# 2. Change the timeframe from M5 to H1 (Tickerall usually uses "M5" or "5m")
# We search for common timeframe strings in this file
s = s.replace('"M5"', '"H1"')
s = s.replace("'M5'", "'H1'")
s = s.replace('"5m"', '"1h"')
s = s.replace("'5m'", "'1h'")
s = s.replace('"m5"', '"h1"')

open(p, "w").write(s)
print("✅ Expanded live pairs and switched timeframe to H1")
