p = ".github/workflows/retrain.yml"
s = open(p).read()

# We make the git add commands safe (silently ignore if file doesn't exist)
s = s.replace("git add winning_dna.json", "git add winning_dna.json 2>/dev/null || true")
s = s.replace("git add council_state.json", "git add council_state.json 2>/dev/null || true")
s = s.replace("git add models/", "git add models/ 2>/dev/null || true")
s = s.replace("git add adaptive_state.json", "git add adaptive_state.json 2>/dev/null || true")

open(p, "w").write(s)
print("✅ Fixed retrain.yml to safely ignore missing files.")
