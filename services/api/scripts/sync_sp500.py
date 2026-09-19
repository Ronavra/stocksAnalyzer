import csv, io, sys
from datetime import date
from pathlib import Path
import httpx
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

# Public S&P 500 constituent CSV maintained by DataHub.
SOURCE="https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"

def normalize_ticker(ticker):
    # FMP commonly represents class tickers with a dash.
    return ticker.strip().replace(".","-")

def main():
    response=httpx.get(SOURCE,timeout=30,follow_redirects=True)
    response.raise_for_status()
    rows=list(csv.DictReader(io.StringIO(response.text)))
    db=get_supabase(); today=str(date.today())
    active=[]
    for r in rows:
        ticker=normalize_ticker(r["Symbol"])
        payload={"ticker":ticker,"name":r.get("Security") or ticker,"sector":r.get("GICS Sector"),
                 "industry":r.get("GICS Sub-Industry"),"is_sp500":True,"active":True}
        saved=db.table("companies").upsert(payload,on_conflict="ticker").execute().data or []
        if saved:
            cid=saved[0]["id"]; active.append(cid)
            db.table("index_memberships").upsert({"company_id":cid,"index_code":"SP500","effective_from":today,
                "source":"datasets/s-and-p-500-companies","source_url":SOURCE,"captured_at":today},
                on_conflict="company_id,index_code,effective_from").execute()
    # Do not deactivate other companies/benchmarks; only clear stale S&P membership flag.
    current=(db.table("companies").select("id").eq("is_sp500",True).execute().data or [])
    for c in current:
        if c["id"] not in active:
            db.table("companies").update({"is_sp500":False}).eq("id",c["id"]).execute()
    print(f"S&P 500 universe synced: {len(active)} companies")

if __name__=="__main__":
    main()
