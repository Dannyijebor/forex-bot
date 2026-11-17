import re

p = "auto_trader.py"
s = open(p).read()

# We match the exact block from "side = None" to the end of the Council checks
pattern = re.compile(
    r'        side = None.*?blocked_by_regime"\n            continue', 
    re.DOTALL
)

clean_block = '''        side = None
        if row["buy_ok"] == "Y" and row["sell_ok"] != "Y":
            side = "BUY"
        elif row["sell_ok"] == "Y" and row["buy_ok"] != "Y":
            side = "SELL"
        elif row["buy_ok"] == "Y" and row["sell_ok"] == "Y":
            mu = float(row.get("meta_up", 0) or 0)
            md = float(row.get("meta_down", 0) or 0)
            side = "BUY" if mu >= md else "SELL"

        if side is None:
            df.at[idx, "label"] = "no_signal"
            updated += 1
            continue

        # --- COUNCIL CHAMPION LOGIC (APPLIED AFTER SIDE IS DETERMINED) ---
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
    print("✅ Fixed the order! Side is now determined BEFORE applying council logic.")
else:
    print("❌ Could not find the block. We may need to look at the file manually.")
