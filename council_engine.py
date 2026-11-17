import pandas as pd
import json
import os
import time
from datetime import datetime, timezone

print("=== CONVENING THE COUNCIL OF MODELS ===")

STATE_FILE = "council_state.json"
SIEVE_DAYS = 14 # Only models older than 14 days can challenge the champion

# 1. Initialize the Council if it doesn't exist
if not os.path.exists(STATE_FILE):
    initial_state = {
        "champion": {"id": "default_live", "dna": {"thresh": 0.65, "flip_buy": 1}, "drawdown_limit": -50.0},
        "challengers": [
            {"id": f"challenger_{i}", "birth": datetime.now(timezone.utc).isoformat(), "dna": {"thresh": 0.65 + (i*0.02), "flip_buy": i%2}, "sim_pnl": 0.0} for i in range(10)
        ]
    }
    with open(STATE_FILE, "w") as f:
        json.dump(initial_state, f, indent=4)
    print("Council initialized with 10 new challengers.")
    exit()

# 2. Load State and Data
with open(STATE_FILE, "r") as f:
    council = json.load(f)

try:
    df = pd.read_csv("signals_log.csv", low_memory=False)
    df = df[df["label"].isin(["win", "loss"])].dropna(subset=["label_pnl_pips"])
    df["label_pnl_pips"] = df["label_pnl_pips"].astype(float)
except Exception as e:
    print("Council meeting aborted: No valid data.")
    exit()

# 3. Simulate the Challengers (Isolated Testing)
now = datetime.now(timezone.utc)
for ch in council["challengers"]:
    # Calculate PnL using their specific DNA
    # In a real system, this would use vectorized pandas operations for speed
    pnl = 0
    for _, row in df.tail(500).iterrows(): # Only look at the recent 500 signals
        conf = max(row.get("meta_up", 0), row.get("meta_down", 0))
        if conf >= ch["dna"]["thresh"]:
            trade_pnl = row["label_pnl_pips"]
            side = "BUY" if row.get("buy_ok") == "Y" else "SELL"
            if side == "BUY" and ch["dna"]["flip_buy"] == 1:
                trade_pnl = -trade_pnl
            pnl += trade_pnl
    ch["sim_pnl"] = round(pnl, 2)

# 4. The Sieving Process (Genetic Elimination)
# Sort challengers by simulated PnL (highest first)
council["challengers"] = sorted(council["challengers"], key=lambda x: x["sim_pnl"], reverse=True)

# Keep the top 7, eliminate the bottom 3
council["challengers"] = council["challengers"][:7]

# Breed 3 new challengers from the DNA of the top 2
top_dna = council["challengers"][0]["dna"]
second_dna = council["challengers"][1]["dna"]

for i in range(3):
    mutated_dna = {
        "thresh": (top_dna["thresh"] + second_dna["thresh"]) / 2 + (0.01 * i),
        "flip_buy": top_dna["flip_buy"] if i % 2 == 0 else second_dna["flip_buy"]
    }
    council["challengers"].append({
        "id": f"challenger_gen2_{i}_{int(time.time())}",
        "birth": now.isoformat(),
        "dna": mutated_dna,
        "sim_pnl": 0.0
    })

# 5. The "2-Week Rule" Promotion
# Only a challenger older than 14 days can become the champion
best_challenger = council["challengers"][0]
birth_date = datetime.fromisoformat(best_challenger["birth"])
age_days = (now - birth_date).days

if age_days >= SIEVE_DAYS and best_challenger["sim_pnl"] > 100: # Must be profitable
    print(f"🚨 PROMOTION: Challenger {best_challenger['id']} has survived {age_days} days and proved itself!")
    print(f"New DNA: {best_challenger['dna']}")
    council["champion"]["dna"] = best_challenger["dna"]
    council["champion"]["id"] = f"champion_{int(time.time())}"

with open(STATE_FILE, "w") as f:
    json.dump(council, f, indent=4)
    
print("Council meeting concluded. State saved.")
