import pandas as pd
import json
import os
import time
from datetime import datetime, timezone

print("=== INITIATING OVERSEER ENGINE (20-MODEL ENSEMBLE) ===")
STATE_FILE = "council_state.json"
SIEVE_DAYS = 14
MAX_CHALLENGERS = 20

# 1. LOAD DATA
try:
    df = pd.read_csv("signals_log.csv", low_memory=False)
    df = df[df["label"].isin(["win", "loss"])].dropna(subset=["label_pnl_pips"])
    df["label_pnl_pips"] = df["label_pnl_pips"].astype(float)
    df["ts_utc"] = pd.to_datetime(df["ts_utc"])
    recent = df.tail(2000).copy() # Look at the last 2000 trades for context
    recent['hour'] = recent['ts_utc'].dt.hour
    recent['side'] = recent.apply(lambda r: "BUY" if r.get("buy_ok") == "Y" else "SELL", axis=1)
except Exception as e:
    print("Overseer aborted: No valid data.", e)
    exit()

# 2. THE DIAGNOSTICS ENGINES (Scouts)
def run_diagnostics(df):
    print("\n🔍 [DIAGNOSTICS] Running 5 Scout Engines...")
    flaws = []
    
    # Scout 1: Worst Pair+Side
    perf = df.groupby(['symbol', 'side'])['label_pnl_pips'].sum().sort_values()
    if perf.iloc[0] < -50: flaws.append({"type": "block_pair", "target": f"{perf.index[0][0]}_{perf.index[0][1]}", "loss": perf.iloc[0]})
    
    # Scout 2: Worst Session (Time of Day)
    perf_hour = df.groupby('hour')['label_pnl_pips'].sum().sort_values()
    if perf_hour.iloc[0] < -50: flaws.append({"type": "block_hour", "target": int(perf_hour.index[0]), "loss": perf_hour.iloc[0]})

    # Scout 3: The "Anti-Predictive" Signal (AUC < 0.45)
    if 'meta_up' in df.columns:
        buy_df = df[df['side'] == 'BUY']
        if len(buy_df) > 100 and buy_df['label_pnl_pips'].sum() < 0:
            flaws.append({"type": "flip_buy", "target": "ALL", "loss": buy_df['label_pnl_pips'].sum()})

    # Scout 4: Global Negative Expectancy
    if df['label_pnl_pips'].sum() < 0:
        flaws.append({"type": "sniper", "target": 0.85, "loss": df['label_pnl_pips'].sum()})

    # Scout 5: Volatility Mismatch (If high spread/high vol trades are losing)
    if 'regime' in df.columns:
        vol_perf = df[df['regime'].isin(['volatile', 'trending'])]['label_pnl_pips'].sum()
        if vol_perf < -50: flaws.append({"type": "block_regime", "target": "volatile", "loss": vol_perf})

    for f in flaws:
        print(f"  🚨 FLAW: {f['type']} on {f['target']} (Loss: {f['loss']:.1f} pips)")
    return flaws

# 3. THE COUNCIL ENGINES (Strategists)
def create_variants(flaws):
    print("\n🧠 [COUNCIL] Generating 20 Targeted Variants...")
    variants = []
    
    # Generate variants based on each flaw
    for flaw in flaws:
        base_dna = {"thresh": 0.65, "flip_buy": 1}
        
        if flaw["type"] == "block_pair":
            variants.append({"id": f"council_block_pair_{int(time.time())}_{len(variants)}", "birth": datetime.now(timezone.utc).isoformat(), "dna": {**base_dna, "block_pair": flaw["target"]}, "sim_pnl": 0.0})
        elif flaw["type"] == "block_hour":
            variants.append({"id": f"council_block_hour_{int(time.time())}_{len(variants)}", "birth": datetime.now(timezone.utc).isoformat(), "dna": {**base_dna, "block_hour": flaw["target"]}, "sim_pnl": 0.0})
        elif flaw["type"] == "flip_buy":
            variants.append({"id": f"council_flip_all_{int(time.time())}_{len(variants)}", "birth": datetime.now(timezone.utc).isoformat(), "dna": {**base_dna, "flip_buy": 1}, "sim_pnl": 0.0})
        elif flaw["type"] == "sniper":
            variants.append({"id": f"council_sniper_{int(time.time())}_{len(variants)}", "birth": datetime.now(timezone.utc).isoformat(), "dna": {**base_dna, "thresh": 0.85}, "sim_pnl": 0.0})
        elif flaw["type"] == "block_regime":
            variants.append({"id": f"council_block_regime_{int(time.time())}_{len(variants)}", "birth": datetime.now(timezone.utc).isoformat(), "dna": {**base_dna, "block_regime": flaw["target"]}, "sim_pnl": 0.0})

    # Fill the rest with genetic variations of the base DNA
    while len(variants) < MAX_CHALLENGERS:
        variants.append({
            "id": f"council_mutation_{int(time.time())}_{len(variants)}",
            "birth": datetime.now(timezone.utc).isoformat(),
            "dna": {"thresh": 0.60 + (len(variants) * 0.02), "flip_buy": len(variants) % 2},
            "sim_pnl": 0.0
        })
    return variants

# 4. THE OVERSEER ENGINE (The Judge)
def overseer_judgment(challengers, df):
    print("\n⚖️ [OVERSEER] Simulating 20 Models against the last 2000 signals...")
    
    # Simulate all models
    for ch in challengers:
        pnl = 0
        for _, row in df.iterrows():
            # Apply blocks
            if ch["dna"].get("block_pair") == f"{row['symbol']}_{row['side']}": continue
            if ch["dna"].get("block_hour") == row['hour']: continue
            if ch["dna"].get("block_regime") == row.get('regime'): continue
            
            conf = max(row.get("meta_up", 0), row.get("meta_down", 0))
            if conf >= ch["dna"]["thresh"]:
                trade_pnl = row["label_pnl_pips"]
                if row['side'] == "BUY" and ch["dna"].get("flip_buy", 1) == 1:
                    trade_pnl = -trade_pnl
                pnl += trade_pnl
        ch["sim_pnl"] = round(pnl, 2)

    # Sort by most profitable
    challengers = sorted(challengers, key=lambda x: x["sim_pnl"], reverse=True)
    
    print("\n🏆 TOP 5 CHALLENGERS (The Hungry Ones):")
    for i in range(5):
        print(f"  {i+1}. {challengers[i]['id']} | DNA: {challengers[i]['dna']} | Profit: {challengers[i]['sim_pnl']} pips")

    # Keep Top 10, Breed 10 new ones
    survivors = challengers[:10]
    print("\n🧬 [OVERSEER] Eliminating bottom 10. Breeding top 10...")
    
    offspring = []
    for i in range(10):
        parent = survivors[i % 10]
        offspring.append({
            "id": f"overseer_breed_{int(time.time())}_{i}",
            "birth": datetime.now(timezone.utc).isoformat(),
            "dna": parent["dna"].copy(),
            "sim_pnl": 0.0
        })
    
    return survivors + offspring

# 5. THE MAIN EXECUTION LOOP
if not os.path.exists(STATE_FILE):
    council = {"champion": {"id": "default_live", "dna": {"thresh": 0.65, "flip_buy": 1}}, "challengers": []}
else:
    with open(STATE_FILE, "r") as f:
        council = json.load(f)

# Run the tiers
flaws = run_diagnostics(recent)
new_variants = create_variants(flaws)
council["challengers"].extend(new_variants)

# Deduplicate and cap at 20
seen = set()
unique_challengers = []
for ch in council["challengers"]:
    sig = str(ch["dna"].get("block_pair", "")) + str(ch["dna"].get("block_hour", "")) + str(ch["dna"].get("thresh"))
    if sig not in seen:
        seen.add(sig)
        unique_challengers.append(ch)

council["challengers"] = overseer_judgment(unique_challengers, recent)

# 6. PROMOTION CHECK
best = council["challengers"][0]
age = (datetime.now(timezone.utc) - datetime.fromisoformat(best["birth"])).days
print(f"\n👑 Current Champion: {council['champion']['id']} (DNA: {council['champion']['dna']})")
print(f"🔥 Best Challenger: {best['id']} | Age: {age} days | Profit: {best['sim_pnl']} pips")

if age >= SIEVE_DAYS and best["sim_pnl"] > 100:
    print(f"🚨 OVERSEER DECISION: Challenger has proven itself. Replacing Champion!")
    council["champion"] = {"id": best["id"], "dna": best["dna"]}
else:
    print("❌ OVERSEER DECISION: Challenger not ready. Champion retains the throne.")

with open(STATE_FILE, "w") as f:
    json.dump(council, f, indent=4)
print("\nOverseer session complete. State saved.")
