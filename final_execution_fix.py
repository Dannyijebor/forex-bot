p = "auto_trader.py"
s = open(p).read()

# The exact anchor we found in your code
target = '        log("  SIGNAL %s %s (Dukascopy close=%.5f) meta=%.3f" % (symbol, side, price, prob))'

# The code we want to inject right after it
injection = '''

        # --- EXECUTION PATCH: LIVE CONTRARIAN FLIP & COOLDOWN ---
        side = apply_contrarian_logic(symbol, side)
        if is_on_cooldown(symbol):
            log("  %s is on a 60-minute cooldown. Skipping live trade." % symbol)
            return
        # ---------------------------------------------------------
'''

if "EXECUTION PATCH" in s:
    print("SKIP: Already applied.")
elif target in s:
    s = s.replace(target, target + injection, 1)
    open(p, "w").write(s)
    print("✅ Execution Patch Applied Perfectly!")
else:
    print("❌ Could not find the anchor. Please check the log line manually.")
