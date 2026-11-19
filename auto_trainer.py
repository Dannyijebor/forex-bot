import pandas as pd
import numpy as np
import os
import json
import lightgbm as lgb
from datetime import datetime, timezone
import signal_engine_v5

print("=== INITIATING AUTONOMOUS MODEL GENERATOR ===")

# 1. Load Signals Data
try:
    df = pd.read_csv("signals_log.csv", low_memory=False)
    df = df[df["label"].isin(["win", "loss"])].dropna(subset=["label_pnl_pips"])
    df["label_pnl_pips"] = df["label_pnl_pips"].astype(float)
except Exception as e:
    print("Trainer aborted: No valid data.")
    exit()

# 2. Identify Missing Models
target_pairs = list(signal_engine_v5.TICKERALL_SYMBOLS.keys())
missing_models = []

for sym in target_pairs:
    # Check if ANY model file exists for this symbol (json, pkl, txt)
    import glob
    model_files = glob.glob(f"models/{sym.lower()}*/*") + glob.glob(f"models/{sym.lower()}_*/*")
    if not model_files:
        missing_models.append(sym)

if not missing_models:
    print("✅ All 9 pairs already have trained models. Nothing to do.")
    exit()

print(f"🔍 Found {len(missing_models)} pairs missing brains: {missing_models}")

# 3. Train New Models
self_rating_report = []

for sym in missing_models:
    print(f"\n🧠 Training new brain for {sym}...")
    
    # Filter data for this symbol
    sym_df = df[df["symbol"] == sym].copy()
    
    if len(sym_df) < 100:
        print(f"  ⚠️ NOT ENOUGH DATA for {sym} (only {len(sym_df)} trades). It needs to run live for a few more days to collect data.")
        continue
        
    # Prepare features and labels
    # Assuming your df has feature columns like 'primary_up', 'meta_up', 'session_london', etc.
    # We drop the target columns to get the features
    # Drop text columns and keep ONLY numeric features
    drop_cols = ['label', 'label_pnl_pips', 'ts_utc', 'symbol', 'side', 'entry_price', 'ticket']
    X = sym_df.drop(columns=[c for c in drop_cols if c in sym_df.columns], errors='ignore')
    X = X.select_dtypes(include=['number']).fillna(0) # Keep only numbers and fill NaNs
    
    # We create a binary label: 1 if win, 0 if loss
    y = (sym_df['label'] == 'win').astype(int)
    
    # Walk-Forward Split (80% train, 20% test)
    split_idx = int(len(X) * 0.8)
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    # Train LightGBM
    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_test, label=y_test, reference=train_data)
    
    params = {
        'objective': 'binary',
        'metric': 'auc',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.9,
        'verbose': -1
    }
    
    model = lgb.train(
        params,
        train_data,
        num_boost_round=100,
        valid_sets=[valid_data],
        callbacks=[lgb.early_stopping(10, verbose=False)]
    )
    
    # 4. Test and Self-Rate
    auc = model.best_score['valid_0']['auc']
    
    if auc < 0.50:
        rating = "TOXIC (Anti-predictive)"
    elif auc < 0.53:
        rating = "COIN FLIP (No edge)"
    elif auc < 0.58:
        rating = "DECENT (Slight edge)"
    else:
        rating = "SHARP (Strong edge)"
        
    self_rating_report.append(f"  {sym}: AUC {auc:.3f} -> {rating} ({len(sym_df)} trades)")
    print(f"  ✅ Trained {sym}! AUC: {auc:.3f} | Rating: {rating}")
    
    # 5. Save the Model
    save_dir = f"models/{sym.lower()}"
    os.makedirs(save_dir, exist_ok=True)
    model.save_model(f"{save_dir}/model_trees.json")
    print(f"  💾 Saved to {save_dir}/model_trees.json")

# 6. Print the Final Report
print("\n=== 🏆 SELF-RATING REPORT ===")
for line in self_rating_report:
    print(line)
print("============================\n")
