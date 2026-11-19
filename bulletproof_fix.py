import re

p = "auto_trader.py"
s = open(p).read()

# 1. Remove ALL previous attempts to apply the logic to prevent duplicates
s = re.sub(r'\n\s*side = apply_contrarian_logic\(sym, side\)', '', s)
s = re.sub(r'\n\s*side = apply_contrarian_logic\(symbol, side\)', '', s)

# 2. Target the exact block inside label_signals
target_block = """        side = None
        if row["buy_ok"] == "Y" and row["sell_ok"] != "Y":
            side = "BUY"
        elif row["sell_ok"] == "Y" and row["buy_ok"] != "Y":
            side = "SELL"
        elif row["buy_ok"] == "Y" and row["sell_ok"] == "Y":
            mu = float(row.get("meta_up", 0) or 0)
            md = float(row.get("meta_down", 0) or 0)
            side = "BUY" if mu >= md else "SELL"

        if side is None:"""

# 3. Create the fixed block with the logic inserted in the correct order
fixed_block = """        side = None
        if row["buy_ok"] == "Y" and row["sell_ok"] != "Y":
            side = "BUY"
        elif row["sell_ok"] == "Y" and row["buy_ok"] != "Y":
            side = "SELL"
        elif row["buy_ok"] == "Y" and row["sell_ok"] == "Y":
            mu = float(row.get("meta_up", 0) or 0)
            md = float(row.get("meta_down", 0) or 0)
            side = "BUY" if mu >= md else "SELL"

        # Apply the contrarian flip ONLY after the side is fully determined
        if side is not None:
            side = apply_contrarian_logic(sym, side)

        if side is None:"""

if target_block in s:
    s = s.replace(target_block, fixed_block, 1)
    print("✅ Perfectly replaced the label_signals block!")
elif "if side is not None:\n            side = apply_contrarian_logic(sym, side)" in s:
    print("✅ The block is already fixed.")
else:
    print("❌ Could not find the exact block. Let me know and we'll do it manually.")

open(p, "w").write(s)
