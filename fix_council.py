p = "council_engine.py"
s = open(p).read()

old_sim = """    # Simulate all models
    for ch in challengers:
        pnl = 0
        for _, row in df.iterrows():"""

new_sim = """    # Simulate all models (TRUE FORWARD TESTING)
    for ch in challengers:
        pnl = 0
        # Only look at data after the challenger was born!
        birth_date = pd.to_datetime(ch["birth"])
        forward_df = df[df['ts_utc'] > birth_date]
        
        # If the challenger is too new, it gets 0 PnL (it hasn't proven anything yet)
        if len(forward_df) < 10:
            ch["sim_pnl"] = 0.0
            continue

        for _, row in forward_df.iterrows():"""

if "TRUE FORWARD TESTING" in s:
    print("Council Fix SKIP (already applied)")
elif old_sim in s:
    s = s.replace(old_sim, new_sim)
    open(p, "w").write(s)
    print("✅ Council Fix OK: Challengers now only graded on post-birth data")
else:
    print("❌ Council Fix FAILED: Could not find simulation loop")
