import argparse
import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from scripts.ingest_company import ingest

DEFAULT_TICKERS = ["AAPL","MSFT","NVDA","AMZN","GOOGL","META","AVGO","BRK-B","TSLA","JPM"]

async def main():
    parser = argparse.ArgumentParser(description="Ingest a batch of research companies")
    parser.add_argument("tickers", nargs="*", default=DEFAULT_TICKERS)
    args = parser.parse_args()
    failures = []
    for ticker in args.tickers:
        try:
            await ingest(ticker)
        except Exception as exc:
            failures.append((ticker, str(exc)))
            print(f"FAILED {ticker}: {exc}")
    print(f"Completed: {len(args.tickers)-len(failures)}/{len(args.tickers)}")
    if failures:
        raise SystemExit(1)

if __name__ == "__main__":
    asyncio.run(main())
