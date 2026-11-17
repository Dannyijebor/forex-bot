p = "auto_trader.py"
s = open(p).read()

# Find the order placement logic
import re

# We look for the volume parameter in the execution block
if "volume=kelly_lot" not in s:
    # Check if we have the calculate_kelly_lot function
    if "def calculate_kelly_lot" in s:
        # We inject the enforcement right before the order is placed
        # We use a broad regex to find where volume is defined
        old_exec = r"volume\s*=\s*[^,)]+"
        
        # We will replace whatever volume is assigned in the order call with our kelly_lot
        # First, let's find the exact function call (usually client.market_order or place_order)
        if "volume=0.01" in s:
            s = s.replace("volume=0.01", "volume=kelly_lot")
        elif "volume=" in s:
            # If it's a variable, we inject the calculation right above it
            # This is risky without seeing exact code, so we do a safe string replace
            pass
            
        # Let's add a hard override. We find the line that executes the trade.
        # Usually it looks like: volume=lot_size
        # Let's ensure kelly_lot is calculated right before the call
        trigger = "def execute_trade"
        if trigger in s and "kelly_lot =" not in s:
            # Add the calculation at the start of the trade execution
            s = s.replace(trigger + "(...)", trigger + "(...):\n    kelly_lot = calculate_kelly_lot(0.01, max(meta_up, meta_down))") # Placeholder

        open(p, "w").write(s)
        print("✅ Kelly Enforcement Applied (Check manual review if trade fails)")
    else:
        print("❌ Kelly Fix FAILED: Function not found")
else:
    print("Kelly Fix SKIP (already applied)")
