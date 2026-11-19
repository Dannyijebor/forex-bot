import os
from dotenv import load_dotenv
from tickerall import Tickerall
import signal_engine_v5

# Load credentials
load_dotenv()

api_key = os.getenv("TICKERALL_API_KEY")
server = os.getenv("EXNESS_SERVER")
login = os.getenv("EXNESS_LOGIN")
password = os.getenv("EXNESS_PASSWORD")

print(f"🔌 Connecting to Exness Demo ({server})...")
client = Tickerall(api_key=api_key)

try:
    # 1. Connect
    session = client.sessions.start(
        broker="mt5", server=server, account=int(login), 
        password=password, terminal_type="MOBILE"
    )
    account_id = session.account_id
    print(f"✅ Connected! Account ID: {account_id}\n")
    
    # 2. Force the updated symbol list (with 'm' suffix) into the signal engine
    signal_engine_v5.TICKERALL_SYMBOLS.update({
        "AUDUSD": "AUDUSDm", "USDCAD": "USDCADm", "NZDUSD": "NZDUSDm",
        "EURGBP": "EURGBPm", "EURJPY": "EURJPYm", "GBPJPY": "GBPJPYm"
    })
    
    targets = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "NZDUSD", "EURGBP", "EURJPY", "GBPJPY"]
    
    print("🔍 Testing H1 Bar Fetch for all 9 pairs:")
    for t in targets:
        try:
            # We use the exact function auto_trader uses to get data
            df = signal_engine_v5.fetch_pair_live(client, account_id, t, count=10)
            if df is not None and len(df) > 0:
                print(f"  ✅ {t} -> SUCCESS! (Latest Close: {df.iloc[-1]['Close']})")
            else:
                print(f"  ❌ {t} -> FAILED (Symbol exists but no data returned)")
        except Exception as e:
            print(f"  ❌ {t} -> FAILED (Broker does not recognize this symbol)")

except Exception as e:
    print(f"❌ Connection Error: {e}")
