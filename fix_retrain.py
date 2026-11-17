p = "retrain_models.py"
s = open(p).read()

if "TIME-SERIES SPLIT" not in s:
    split_code = """
    # --- INSTITUTIONAL PATCH: TIME-SERIES SPLIT ---
    # Ensure the data is sorted by time
    df = df.sort_values('ts_utc')
    
    # Split chronologically (no random shuffling!)
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]
    
    X_train = train_df.drop(columns=['label', 'label_pnl_pips'], errors='ignore')
    y_train = train_df['label']
    X_val = test_df.drop(columns=['label', 'label_pnl_pips'], errors='ignore')
    y_val = test_df['label']
    # ----------------------------------------------
"""
    s = s.replace("X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2)", split_code)
    s = s.replace("X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2)", split_code)
    print("✅ Walk-Forward Split Injected")

if "CORRELATION AUTOPSY" not in s:
    corr_code = """
    # --- INSTITUTIONAL PATCH: CORRELATION AUTOPSY ---
    try:
        print("\\n=== 🔬 CORRELATION AUTOPSY (Losing Features) ===")
        # Calculate correlation of every feature against the actual PnL
        corr_matrix = train_df.corr()['label_pnl_pips'].sort_values()
        worst_features = corr_matrix.head(3)
        for feat, corr in worst_features.items():
            if feat != 'label_pnl_pips':
                print(f"  🔻 {feat}: Correlation = {corr:.3f} (High correlation means it CAUSES losses)")
        print("=================================================\\n")
    except Exception as e:
        pass
    # ------------------------------------------------
"""
    s = s.replace("if __name__", corr_code + "\nif __name__")
    open(p, "w").write(s)
    print("✅ Correlation Autopsy Injected")
else:
    print("Retrain Fix SKIP (already applied)")
