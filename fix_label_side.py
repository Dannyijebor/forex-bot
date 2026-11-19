import re

p = "auto_trader.py"
s = open(p).read()

# We are going to find the exact label_signals loop block and fix the order
pattern = re.compile(
    r'        # --- COUNCIL CHAMPION LOGIC \(APPLIED AFTER SIDE IS DETERMINED\) ---.*?# -----------------------------------------------------------------', 
    re.DOTALL
)

# We replace it with a perfectly ordered block
clean_block = '''        # --- COUNCIL CHAMPION LOGIC (APPLIED AFTER SIDE IS DETERMINED) ---
        side = apply_contrarian_logic(sym, side)
        champ_dna = COUNCIL_STATE["champion"]["dna"]
        
        if champ_dna.get("block_pair") == f"{sym}_{side}":
            df.at[idx, "label"] = "blocked_by_council"
            continue
        if champ_dna.get("block_hour") == ts.hour:
            df.at[idx, "label"] = "blocked_by_hour"
            continue
        if champ_dna.get("block_regime") == row.get("regime"):
            df.at[idx, "label"] = "blocked_by_regime"
            continue
        # -----------------------------------------------------------------'''

if pattern.search(s):
    s = pattern.sub(clean_block, s)
    open(p, "w").write(s)
    print("✅ Fixed label_signals variable order.")
else:
    # Fallback: If regex fails, let's just remove the injected line inside label_signals
    # and let the live execution loop handle it (since label_signals is just for historical data).
    bad_line = '        side = apply_contrarian_logic(symbol, side)\n'
    if bad_line in s:
        s = s.replace(bad_line, '', 1)
        open(p, "w").write(s)
        print("✅ Removed faulty injected line.")
    else:
        print("⚠️ Could not find the broken block. Check manually.")

