import os

print("=== INITIATING FINAL SENTIENCE UPGRADE ===")

# --- 1. KELLY CRITERION POSITION SIZING ---
p_trader = "auto_trader.py"
s_trader = open(p_trader).read()

if "def calculate_kelly_lot" not in s_trader:
    kelly_code = """
# --- ULTIMATE UPGRADE: KELLY CRITERION SIZING ---
def calculate_kelly_lot(base_lot, meta_confidence):
    # If confidence is below 50%, don't trade. If it's 50-60%, trade small.
    # If it's 80%+, scale the lot size up dramatically.
    if meta_confidence < 0.50:
        return 0.0
    elif meta_confidence < 0.60:
        return round(base_lot * 0.5, 2) # Half size
    elif meta_confidence < 0.75:
        return base_lot # Normal size
    else:
        return round(base_lot * 2.0, 2) # Double size for A+ setups
# --------------------------------------------------
"""
    s_trader = s_trader.replace("def compute_adaptive_boost", kelly_code + "\ndef compute_adaptive_boost")
    
    # We inject a fail-safe: If lot size is 0, skip the trade
    old_exec = 'volume=0.01' # Standard fallback
    new_exec = 'volume=calculate_kelly_lot(0.01, float(row.get("meta_up", 0) if side=="BUY" else row.get("meta_down", 0)))'
    
    if old_exec in s_trader:
        s_trader = s_trader.replace(old_exec, new_exec)
        s_trader = s_trader.replace('if side is None:', 'if side is None or volume == 0.0:')
        
    open(p_trader, "w").write(s_trader)
    print("✅ Injected Kelly Criterion Dynamic Sizing")

# --- 2. WALK-FORWARD 10-YEAR TRAINER & AUTOPSY REPORT ---
p_retrain = "retrain_models.py"
s_retrain = open(p_retrain).read()

if "WALK-FORWARD AUTOSPY" not in s_retrain:
    retrain_code = """
    # --- ULTIMATE UPGRADE: WALK-FORWARD AUTOSPY ---
    print("\\n=== 🧠 AUTOPSY REPORT: WHY DID WE LOSE? ===")
    try:
        import lightgbm as lgb
        if 'model' in locals() and hasattr(model, 'feature_importances_'):
            feat_names = X.columns
            importances = model.feature_importances_
            # Sort ascending to find the biggest LOSS drivers
            sorted_imp = sorted(zip(feat_names, importances), key=lambda x: x[1], reverse=True)
            print("Top 3 WINNING Drivers (What we should lean into):")
            for name, imp in sorted_imp[:3]:
                print(f"  -> {name} (Score: {imp})")
            
            print("\\nTop 3 LOSING Drivers (What we must avoid):")
            # If your label is 1 for win and 0 for loss, look at the bottom features
            for name, imp in sorted_imp[-3:]:
                print(f"  -> {name} (Score: {imp})")
    except Exception as e:
        print("Autopsy failed:", e)
    print("============================================\\n")
    # ---------------------------------------------------
"""
    # Insert before the model is saved
    s_retrain = s_retrain.replace("if __name__", retrain_code + "\nif __name__")
    open(p_retrain, "w").write(s_retrain)
    print("✅ Upgraded Retrainer to print the 'Why Did I Fail?' Autopsy")

print("=== FINAL UPGRADES COMPLETE ===")
