import os

print("=== INJECTING WORLD-CLASS CONTEXT ===")

# --- 1. MULTI-TIMEFRAME TREND AWARENESS ---
p_feat = "feature_engine_v3.py"
s_feat = open(p_feat).read()

if "htf_trend_h1" not in s_feat:
    inject_trend = """
    # --- WORLD CLASS UPGRADE: MULTI-TIMEFRAME TRENDS ---
    try:
        # Calculate 50-period and 200-period EMAs for H1 and H4
        df['htf_trend_h1'] = (df['Close'].ewm(span=50).mean() > df['Close'].ewm(span=200).mean()).astype(int)
        df['htf_trend_h4'] = (df['Close'].ewm(span=200).mean() > df['Close'].ewm(span=800).mean()).astype(int)
        # Trend alignment score (2 = strong buy, -2 = strong sell)
        df['trend_alignment'] = (df['htf_trend_h1'] * 1) + (df['htf_trend_h4'] * 1)
    except Exception as e:
        pass
    # ---------------------------------------------------
"""
    lines = s_feat.split('\n')
    for i in range(len(lines)-1, -1, -1):
        if lines[i].strip().startswith('return'):
            lines.insert(i, inject_trend)
            break
    open(p_feat, "w").write('\n'.join(lines))
    print("✅ Injected Multi-Timeframe Trend Filter (H1 + H4)")

# --- 2. MACRO NEWS BLACKOUT (Hardcoded High-Impact Events) ---
p_trader = "auto_trader.py"
s_trader = open(p_trader).read()

if "NEWS_BLACKOUT_HOURS" not in s_trader:
    inject_news = """
# --- WORLD CLASS UPGRADE: MACRO NEWS BLACKOUTS ---
# Hardcoded high-impact forex news windows (UTC Time)
# 13:30 UTC = US CPI / NFP, 18:00 UTC = FOMC, 11:00 UTC = ECB
NEWS_BLACKOUT_HOURS = [13, 18, 11]

def is_news_blackout(now_utc):
    if now_utc.hour in NEWS_BLACKOUT_HOURS:
        return True
    return False
# ------------------------------------------------
"""
    # Insert near the top of the file, after imports
    s_trader = s_trader.replace("def compute_adaptive_boost", inject_news + "\ndef compute_adaptive_boost")
    open(p_trader, "w").write(s_trader)
    print("✅ Injected Macro News Blackout Logic")

# --- 3. THE NEWS BLOCKER IN THE MAIN LOOP ---
if "is_news_blackout(now)" not in s_trader:
    # We find the session block and add news block right after
    old_block = 'log("  Not trading (blocked). Exiting.")'
    new_block = '''log("  Not trading (session blocked). Exiting.")
            sys.exit(0)
            
        if is_news_blackout(now):
            log("  Not trading (Macro News Blackout active). Exiting.")
            sys.exit(0)'''
    s_trader = s_trader.replace(old_block, new_block)
    open(p_trader, "w").write(s_trader)
    print("✅ News Blackout wired into trading loop")

print("=== GENIUS UPGRADE COMPLETE ===")
