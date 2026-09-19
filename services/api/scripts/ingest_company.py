import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from app.db.client import get_supabase
from app.providers.fmp import FMPProvider

async def ingest(ticker: str):
    ticker = ticker.upper().strip()
    provider = FMPProvider()
    db = get_supabase()

    quote = await provider.quote(ticker)
    financials = await provider.financials(ticker)
    try:
        profile_result = await provider.profile(ticker)
        profile_rows = profile_result.value or []
        profile = profile_rows[0] if isinstance(profile_rows, list) and profile_rows else profile_rows
    except Exception as exc:
        print(f"Profile unavailable for {ticker}: {exc}")
        profile = {}
    q = quote.value[0] if isinstance(quote.value, list) and quote.value else quote.value
    company_name = (q or {}).get("name") or ticker

    company = db.table("companies").upsert(
        {"ticker": ticker, "name": company_name, "sector": profile.get("sector"), "industry": profile.get("industry")},
        on_conflict="ticker",
    ).execute()
    row = company.data[0]
    company_id = row["id"]

    statements = financials.value
    income_rows = statements.get("income") or []
    balance_by_date = {x.get("date"): x for x in (statements.get("balance") or [])}
    cash_by_date = {x.get("date"): x for x in (statements.get("cashflow") or [])}

    saved = 0
    for inc in income_rows[:5]:
        date = inc.get("date")
        if not date:
            continue
        bal = balance_by_date.get(date, {})
        cash = cash_by_date.get(date, {})
        payload = {
            "company_id": company_id,
            "period_end": date,
            "period_type": "annual",
            "revenue": inc.get("revenue"),
            "operating_income": inc.get("operatingIncome"),
            "net_income": inc.get("netIncome"),
            "eps_diluted": inc.get("epsDiluted") if inc.get("epsDiluted") is not None else inc.get("epsdiluted"),
            "free_cash_flow": cash.get("freeCashFlow"),
            "capex": cash.get("capitalExpenditure"),
            "cash": bal.get("cashAndCashEquivalents"),
            "total_debt": bal.get("totalDebt"),
            "source": "fmp",
        }
        db.table("financial_metrics").upsert(
            payload, on_conflict="company_id,period_end,period_type"
        ).execute()
        saved += 1

    print(f"Ingested {ticker}: company_id={company_id}, annual periods={saved}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", help="US ticker, e.g. AAPL")
    args = parser.parse_args()
    asyncio.run(ingest(args.ticker))

if __name__ == "__main__":
    main()
