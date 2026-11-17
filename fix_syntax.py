import re

p = "auto_trader.py"
s = open(p).read()

# 1. Clean up the broken function
broken_func = """def apply_contrarian_logic(symbol, side):
    # COUNCIL CHAMPION LOGIC
    champ_dna = COUNCIL_STATE["champion"]["dna"]
    flip_allowed = champ_dna.get("flip_buy", 1)
    
    # Check if the Champion DNA explicitly blocks this setup
    if champ_dna.get("block_pair") == f"{sym}_{side}":
        df.at[idx, "label"] = "blocked_by_council"
        continue
    if champ_dna.get("block_hour") == ts.hour:
        df.at[idx, "label"] = "blocked_by_hour"
        continue
    if champ_dna.get("block_regime") == row.get("regime"):
        df.at[idx, "label"] = "blocked_by_regime"
        continue

    if symbol in CONTRARIAN_BUY_PAIRS and side == "BUY" and flip_allowed == 1:
        print(f"  ⚠️ CONTRARIAN FLIP: Primary model wanted BUY on {symbol}. Flipping to SELL.")
        return "SELL"
    return side"""

clean_func = """def apply_contrarian_logic(symbol, side):
    # COUNCIL CHAMPION LOGIC
    champ_dna = COUNCIL_STATE["champion"]["dna"]
    flip_allowed = champ_dna.get("flip_buy", 1)
    
    if symbol in CONTRARIAN_BUY_PAIRS and side == "BUY" and flip_allowed == 1:
        print(f"  ⚠️ CONTRARIAN FLIP: Primary model wanted BUY on {symbol}. Flipping to SELL.")
        return "SELL"
    return side"""

# Replace the broken function with the clean one
if broken_func in s:
    s = s.replace(broken_func, clean_func)
elif "if champ_dna.get(\"block_pair\") == f\"{sym}_{side}\":" in s:
    # If the exact block doesn't match, use regex to remove the bad lines
    s = re.sub(r'    # Check if the Champion DNA explicitly blocks this setup.*?continue\n', '', s, flags=re.DOTALL)

# 2. Inject the blocking logic INSIDE the loop
# We find where the side is determined in the label_signals loop
anchor = '        side = apply_contrarian_logic(sym, side)'
block_inject = '''        side = apply_contrarian_logic(sym, side)
        
        # --- COUNCIL BLOCKING LOGIC (INSIDE THE LOOP) ---
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
        # ------------------------------------------------'''

if "blocked_by_council" not in s:
    s = s.replace(anchor, block_inject)
    print("✅ Council blocking logic moved INSIDE the loop.")
else:
    print("⚠️ Logic already inside loop, cleaning up function instead.")

open(p, "w").write(s)
print("Fix applied!")
