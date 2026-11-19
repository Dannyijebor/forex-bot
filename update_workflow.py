p = ".github/workflows/retrain.yml"
s = open(p).read()

if "auto_trainer.py" not in s:
    # Insert auto_trainer right after the DNA evolution and before the main retrain
    s = s.replace("python council_engine.py\n          python quantum_dna.py\n          python retrain_models.py", 
                  "python council_engine.py\n          python quantum_dna.py\n          python auto_trainer.py\n          python retrain_models.py")
    
    # Make sure it saves the new models
    if "git add models/ 2>/dev/null" not in s:
        s = s.replace("git add models/ 2>/dev/null || true", "git add models/ 2>/dev/null || true")

    open(p, "w").write(s)
    print("✅ Wired Auto-Trainer into Nightly Workflow")
else:
    print("SKIP: Already wired.")
