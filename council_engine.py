import pandas as pd
import json
import os
import time
from datetime import datetime, timezone

print("=== CONVENING THE COUNCIL OF MODELS ===")
STATE_FILE = "council_state.json"
SIEVE_DAYS = 14

# 1. Load Data
try:
    df = pd.read_csv("signals_log.csv", low_memory=False)
    df = df[df["label"].isin(["win", "loss"])].dropna(subset=["label_pnl_pips"])
    df["label_pnl_pips"] = df["label_pnl_pips"].astype(float)
    recent = df.tail(1000) # Look at the most recent 1000 trades
except Exception as e:
    print("Council meeting aborted: No valid data.")
    exit()

# 2. THE DIAGNOSTIC ENGINE (Root Cause Analysis)
def diagnose_and_create_variants(recent_df):
    print("\n🧠 [DIAGNOSTIC ENGINE] Autopsy of recent performance...")
    variants = []
    
    # Calculate PnL by Symbol and Side
    recent_df['side'] = recent_df.apply(lambda r: "BUY" if r.get("buy_ok") == "Y" else "SELL", axis=1)
    perf = recent_df.groupby(['symbol', 'side'])['label_pnl_pips'].sum().sort_values()
    
    worst_flaw = perf.index[0]
    worst_loss = perf.iloc[0]
    
    if worst_loss < -50:
        sym, side = worst_flaw
        print(f"  🚨 FLAW DETECTED: {sym} {side} is bleeding {worst_loss:.1f} pips.")
        print(f"  📝 THEORY: The primary model is misinterpreting mean-reversion in this specific market direction.")
        print(f"  🛠️ SOLUTION: Deploy a variant that blocks {sym} {side} entirely or flips it.")
        
        # Variant A: The Blocker
        variants.append({
            "id": f"targeted_block_{sym}_{side}_{int(time.time())}",
            "birth": datetime.now(timezone.utc).isoformat(),
            "dna": {"thresh": 0.65, "flip_buy": 1, "block_pair": f"{sym}_{side}"},
            "sim_pnl": 0.0
        })
        
    # Find worst Session (We simulate this by just raising the threshold globally if losses are high)
    if recent_df['label_pnl_pips'].sum() < 0:
        print(f"  🚨 FLAW DETECTED: Global negative expectancy.")
        print(f"  📝 THEORY: The bot is trading too frequently in low-probability setups.")
        print(f"  🛠️ SOLUTION: Deploy a 'Sniper' variant that demands 85% confidence.")
        variants.append({
            "id": f"targeted_sniper_{int(time.time())}",
            "birth": datetime.now(timezone.utc).isoformat(),
            "dna": {"thresh": 0.85, "flip_buy": 1},
            "sim_pnl": 0.0
        })
        
    return variants

# 3. Load or Initialize Council
if not os.path.exists(STATE_FILE):
    council = {
        "champion": {"id": "default_live", "dna": {"thresh": 0.65, "flip_buy": 1}},
        "challengers": []
    }
    # Initialize with 7 random variants
    for i in range(7):
        council["challengers"].append({
            "id": f"random_{i}", "birth": datetime.now(timezone.utc).isoformat(),
            "dna": {"thresh": 0.65 + (i*0.02), "flip_buy": i%2}, "sim_pnl": 0.0
        })
else:
    with open(STATE_FILE, "r") as f:
        council = json.load(f)

# 4. Inject the Targeted Variants from the Diagnostic Brain
targeted_variants = diagnose_and_create_variants(recent)
council["challengers"].extend(targeted_variants)

# 5. Simulate the Challengers (Isolated Testing)
now = datetime.now(timezone.utc)
for ch in council["challengers"]:
    pnl = 0
    for _, row in recent.iterrows():
        conf = max(row.get("meta_up", 0), row.get("meta_down", 0))
        side = "BUY" if row.get("buy_ok") == "Y" else "SELL"
        
        # Check if this variant explicitly blocks this trade
        if ch["dna"].get("block_pair") == f"{row['symbol']}_{side}":
            continue # Skip this trade
            
        if conf >= ch["dna"]["thresh"]:
            trade_pnl = row["label_pnl_pips"]
            if side == "BUY" and ch["dna"].get("flip_buy", 1) == 1:
                trade_pnl = -trade_pnl
            pnl += trade_pnl
    ch["sim_pnl"] = round(pnl, 2)

# 6. The Sieve (Elimination & Breeding)
council["challengers"] = sorted(council["challengers"], key=lambda x: x["sim_pnl"], reverse=True)
council["challengers"] = council["challengers"][:7] # Keep top 7

# Breed 3 new ones from the top 2
if len(council["challengers"]) >= 2:
    top_dna = council["challengers"][0]["dna"]
    second_dna = council["challengers"][1]["dna"]
    for i in range(3):
        council["challengers"].append({
            "id": f"breed_gen2_{i}_{int(time.time())}",
            "birth": now.isoformat(),
            "dna": {"thresh": (top_dna["thresh"] + second_dna["thresh"]) / 2, "flip_buy": top_dna.get("flip_buy", 1)},
            "sim_pnl": 0.0
        })

# 7. Promotion Check (The 14-Day Rule)
best_challenger = council["challengers"][0]
age_days = (now - datetime.fromisoformat(best_challenger["birth"])).days

print(f"\n🏆 Top Challenger: {best_challenger['id']} (Sim PnL: {best_challenger['sim_pnl']} pips)")
if age_days >= SIEVE_DAYS and best_challenger["sim_pnl"] > 100:
    print(f"🚨 PROMOTION: {best_challenger['id']} survived {age_days} days and proved itself!")
    council["champion"]["dna"] = best_challenger["dna"]
    council["champion"]["id"] = best_challenger["id"]

with open(STATE_FILE, "w") as f:
    json.dump(council, f, indent=4)
print("Council meeting concluded. State saved.")
