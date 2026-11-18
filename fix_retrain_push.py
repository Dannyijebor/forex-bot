p = ".github/workflows/retrain.yml"
s = open(p).read()

# Fix the git push to always pull first
if "git pull --rebase origin main && git push" not in s:
    old_push = "git push"
    new_push = "git pull --rebase origin main && git push"
    s = s.replace(old_push, new_push)
    
    open(p, "w").write(s)
    print("✅ Fixed retrain.yml to prevent push rejections!")
else:
    print("SKIP: Already fixed.")
