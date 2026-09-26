import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone, date
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from app.db.client import get_supabase
from app.providers.sec import SECProvider, facts_by_period, quarter_facts_by_period

DURATION_FIELDS=("revenue","operating_income","net_income","eps_diluted","free_cash_flow","capex")

def d(v):
    return date.fromisoformat(v) if isinstance(v,str) else v

def build_ttm_rows(annual_rows, quarter_rows):
    # Derive fiscal Q4 from the annual filing minus the three 10-Q quarters,
    # then build rolling four-quarter TTM rows. filed_date is the latest filing
    # needed for the TTM value, which makes point-in-time joins safe.
    annual=sorted(annual_rows,key=lambda x:x["period_end"])
    quarters=[dict(x) for x in quarter_rows]
    prev_end=None
    for a in annual:
        a_end=d(a["period_end"])
        candidates=[
            q for q in quarters
            if d(q["period_end"])<a_end
            and (prev_end is None or d(q["period_end"])>prev_end)
            and (a_end-d(q["period_end"])).days<=330
        ]
        candidates=sorted(candidates,key=lambda x:x["period_end"])[-3:]
        if len(candidates)>=3:
            q4={"period_end":a["period_end"],"filed_date":a.get("filed_date"),"accn":a.get("accn")}
            for field in DURATION_FIELDS:
                av=a.get(field); vals=[q.get(field) for q in candidates]
                q4[field]=float(av)-sum(float(v) for v in vals) if av is not None and all(v is not None for v in vals) else None
            q4["cash"]=a.get("cash")
            q4["total_debt"]=a.get("total_debt")
            quarters.append(q4)
        prev_end=a_end

    quarters=sorted({q["period_end"]:q for q in quarters}.values(),key=lambda x:x["period_end"])
    out=[]
    for i in range(3,len(quarters)):
        window=quarters[i-3:i+1]
        if (d(window[-1]["period_end"])-d(window[0]["period_end"])).days>430:
            continue
        rec={"period_end":window[-1]["period_end"]}
        for field in DURATION_FIELDS:
            vals=[q.get(field) for q in window]
            rec[field]=sum(float(v) for v in vals) if all(v is not None for v in vals) else None
        rec["cash"]=window[-1].get("cash")
        rec["total_debt"]=window[-1].get("total_debt")
        filed=[q.get("filed_date") for q in window if q.get("filed_date")]
        rec["filed_date"]=max(filed) if filed else None
        rec["accn"]=window[-1].get("accn")
        if sum(rec.get(k) is not None for k in ("revenue","operating_income","net_income","eps_diluted"))>=2:
            out.append(rec)
    return out



async def main():
    p = argparse.ArgumentParser(description="Ingest annual fundamentals from official SEC Company Facts")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--delay", type=float, default=.15)
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--quarters", type=int, default=16)
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
            annual_rows = facts_by_period(result.value, a.years)
            quarter_rows = quarter_facts_by_period(result.value, a.quarters)
            ttm_rows = build_ttm_rows(annual_rows, quarter_rows)
            captured_at=datetime.now(timezone.utc).isoformat()
            n = 0
            for period_type, rows in (("annual", annual_rows), ("quarter", quarter_rows), ("ttm", ttm_rows)):
                for x in rows:
                    payload = {
                        "company_id": company["id"],
                        "period_end": x["period_end"],
                        "period_type": period_type,
                        "revenue": x.get("revenue"),
                        "operating_income": x.get("operating_income"),
                        "net_income": x.get("net_income"),
                        "eps_diluted": x.get("eps_diluted"),
                        "free_cash_flow": x.get("free_cash_flow"),
                        "capex": x.get("capex"),
                        "cash": x.get("cash"),
                        "total_debt": x.get("total_debt"),
                        "source": "sec",
                        "filed_date": x.get("filed_date"),
                        "accession_number": x.get("accn"),
                        "captured_at": captured_at,
                    }
                    db.table("financial_metrics").upsert(
                        payload, on_conflict="company_id,period_end,period_type"
                    ).execute()
                    n += 1
            ok += 1
            saved += n
            print(company["ticker"], "SEC annual=", len(annual_rows), "quarter=", len(quarter_rows), "ttm=", len(ttm_rows))
        except Exception as exc:
            failed += 1
            print(company["ticker"], "SEC unavailable:", exc)

    print(f"Done companies_ok={ok} failed={failed} rows_saved={saved}")


if __name__ == "__main__":
    asyncio.run(main())
