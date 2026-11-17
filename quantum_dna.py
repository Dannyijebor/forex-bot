import pandas as pd
import numpy as np
import json
import random
import os

print("=== INITIATING QUANTUM DNA EVOLUTION ===")

# 1. Load historical data
try:
    df = pd.read_csv("signals_log.csv", low_memory=False)
    df = df[df["label"].isin(["win", "loss"])].dropna(subset=["label_pnl_pips"])
    df["label_pnl_pips"] = df["label_pnl_pips"].astype(float)
except Exception as e:
    print("Evolution aborted: No valid data.", e)
    exit()

if len(df) < 1000:
    print("Not enough data to evolve.")
    exit()

# 2. Define the "DNA" (Parameters to mutate)
# We will mutate the confidence thresholds and the Contrarian logic
current_dna = {
    "EURUSD_thresh": 0.52,
    "GBPUSD_thresh": 0.48,
    "USDJPY_thresh": 0.76,
    "flip_buy_eurusd": 1,
    "flip_buy_gbpusd": 1
}

def simulate_trading(df, dna):
    """Simulate PnL using a specific DNA sequence"""
    total_profit = 0
    for _, row in df.iterrows():
        sym = row["symbol"]
        thresh = dna.get(f"{sym}_thresh", 0.5)
        
        # Check if confidence meets threshold
        conf = max(row.get("meta_up", 0), row.get("meta_down", 0))
        if conf < thresh:
            continue
            
        # Apply Contrarian logic
        pnl = row["label_pnl_pips"]
        side = "BUY" if row.get("buy_ok") == "Y" else "SELL"
        
        if side == "BUY" and dna.get(f"flip_buy_{sym.lower()}", 0) == 1:
            pnl = -pnl # Flip the trade
            
        total_profit += pnl
    return total_profit

# 3. Generate 100 Mutations (Thoughts)
best_dna = current_dna.copy()
best_score = simulate_trading(df, current_dna)
print(f"Baseline Profit: {best_score:.2f} pips")

for i in range(100):
    mutant = current_dna.copy()
    # Mutate thresholds randomly +/- 5%
    for sym in ["EURUSD", "GBPUSD", "USDJPY"]:
        mutant[f"{sym}_thresh"] = max(0.4, min(0.9, mutant[f"{sym}_thresh"] + random.uniform(-0.05, 0.05)))
    
    # Mutate flip logic (50% chance to toggle)
    if random.random() > 0.5: mutant["flip_buy_eurusd"] = 1 - mutant["flip_buy_eurusd"]
    if random.random() > 0.5: mutant["flip_buy_gbpusd"] = 1 - mutant["flip_buy_gbpusd"]
    
    score = simulate_trading(df, mutant)
    
    # If the mutation is better, it becomes the new baseline
    if score > best_score:
        best_score = score
        best_dna = mutant.copy()

# 4. Save the winning DNA
with open("winning_dna.json", "w") as f:
    json.dump(best_dna, f, indent=4)

print(f"Evolution Complete! New Optimized Profit: {best_score:.2f} pips")
print("Saved winning DNA to winning_dna.json")
