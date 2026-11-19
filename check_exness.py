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
    # 1. Connect using the correct session method
    session = client.sessions.start(
        broker="mt5", 
        server=server, 
        account=int(login), 
        password=password,
        terminal_type="MOBILE"
    )
    
    print(f"✅ Connected! Session Object: {session}")
    
    # 2. Fetch symbols. 
    # Note: The session object likely holds the account ID. We will try to grab it dynamically.
    # If this fails, we will see the error in the output.
    try:
        symbols = client.symbols(session)
        print("📥 Successfully fetched symbol list!")
        
        targets = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
        print("\n🔍 Searching for our 9 pairs:")
        
        for t in targets:
            matches = [s["name"] for s in symbols if s["name"].startswith(t)]
            if matches:
                print(f"  ✅ {t} -> Found as: {matches}")
            else:
                print(f"  ❌ {t} -> NOT FOUND on this account")
    except Exception as e:
        print(f"⚠️ Could not fetch symbols directly using session object. Error: {e}")
        
except Exception as e:
    print(f"❌ Connection Error: {e}")
