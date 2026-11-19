import os
from dotenv import load_dotenv
from tickerall import Tickerall

# Load credentials
load_dotenv()

api_key = os.getenv("TICKERALL_API_KEY")
server = os.getenv("EXNESS_SERVER")
login = os.getenv("EXNESS_LOGIN")
password = os.getenv("EXNESS_PASSWORD")

if not all([api_key, server, login, password]):
    print("❌ Missing credentials in .env file.")
    exit()

print(f"🔌 Connecting to Exness Demo ({server}) as {login}...")
client = Tickerall(api_key=api_key)

try:
    # 1. Connect to the MT5 account
    account_id = client.connect(
        broker="mt5", 
        server=server, 
        account=int(login), 
        password=password
    )
    print(f"✅ Connected! Account ID: {account_id}")
    
    # 2. Fetch all available symbols
    print("📥 Downloading broker symbol list...")
    symbols = client.symbols(account_id)
    
    # 3. Check for our target pairs
    targets = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
    found = []
    
    print("\n🔍 Searching for our 9 pairs:")
    for t in targets:
        # Find any symbol that starts with the pair name (e.g., EURUSDm, EURUSD.raw)
        matches = [s["name"] for s in symbols if s["name"].startswith(t)]
        if matches:
            print(f"  ✅ {t} -> Found as: {matches}")
            found.append(matches[0]) # Save the first match
        else:
            print(f"  ❌ {t} -> NOT FOUND on this account")
            
    print(f"\nTotal symbols on account: {len(symbols)}")
    
except Exception as e:
    print(f"❌ Error: {e}")
