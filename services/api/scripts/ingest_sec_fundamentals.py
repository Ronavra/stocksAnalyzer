import argparse
import asyncio
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from app.db.client import get_supabase
from app.providers.sec import SECProvider, facts_by_period


async def main():
    p = argparse.ArgumentParser(description="Ingest annual fundamentals from official SEC Company Facts")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--delay", type=float, default=.15)
    p.add_argument("--years", type=int, default=10)
    a = p.parse_args()

    db = get_supabase()
    provider = SECProvider()
    companies = (
        db.table("companies")
        .select("id,ticker,cik")
        .eq("is_sp500", True)
        .order("ticker")
        .execute()
        .data
        or []
    )

    if a.tickers:
        wanted = {x.upper() for x in a.tickers}
        companies = [x for x in companies if x["ticker"] in wanted]
    elif not a.all:
        companies = companies[a.offset : a.offset + a.batch_size]

    ticker_map = await provider.ticker_map()
    ok = failed = saved = 0

    for i, company in enumerate(companies):
        if i and a.delay:
            time.sleep(a.delay)

        if not company.get("cik"):
            company["cik"] = ticker_map.get(company["ticker"])
            if company.get("cik"):
                db.table("companies").update({"cik": company["cik"]}).eq("id", company["id"]).execute()

        if not company.get("cik"):
            print(company["ticker"], "missing SEC CIK mapping")
            failed += 1
            continue

        try:
            result = await provider.company_facts(company["cik"])
            rows = facts_by_period(result.value, a.years)
            n = 0
            for x in rows:
                payload = {
                    "company_id": company["id"],
                    "period_end": x["period_end"],
                    "period_type": "annual",
                    "revenue": x.get("revenue"),
                    "operating_income": x.get("operating_income"),
                    "net_income": x.get("net_income"),
                    "eps_diluted": x.get("eps_diluted"),
                    "free_cash_flow": x.get("free_cash_flow"),
                    "capex": x.get("capex"),
                    "cash": x.get("cash"),
                    "total_debt": x.get("total_debt"),
                    "source": "sec",
                }
                db.table("financial_metrics").upsert(
                    payload, on_conflict="company_id,period_end,period_type"
                ).execute()
                n += 1
            ok += 1
            saved += n
            print(company["ticker"], "SEC rows=", n)
        except Exception as exc:
            failed += 1
            print(company["ticker"], "SEC unavailable:", exc)

    print(f"Done companies_ok={ok} failed={failed} rows_saved={saved}")


if __name__ == "__main__":
    asyncio.run(main())
