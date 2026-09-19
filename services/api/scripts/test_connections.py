import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from app.db.client import get_supabase
from app.providers.fmp import FMPProvider

async def main():
    print("Checking environment...")
    required = ["FMP_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise SystemExit("Missing: " + ", ".join(missing))

    print("Checking FMP...")
    quote = await FMPProvider().quote("AAPL")
    rows = quote.value
    if not rows:
        raise SystemExit("FMP returned no AAPL quote")
    print("FMP OK")

    print("Checking Supabase...")
    db = get_supabase()
    result = db.table("companies").select("id,ticker").limit(1).execute()
    print(f"Supabase OK (companies rows returned: {len(result.data or [])})")
    print("All connections OK")

if __name__ == "__main__":
    asyncio.run(main())
