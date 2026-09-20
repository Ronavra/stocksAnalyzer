import argparse,asyncio,sys,time
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.fmp import FMPProvider

def num(v):
    try: return None if v in (None,"","None") else float(v)
    except (TypeError,ValueError): return None

def by_date(rows):
    return {str(r.get("date")):r for r in (rows or []) if r.get("date")}

async def ingest_company(db,provider,c):
    data=(await provider.financials(c["ticker"])).value or {}
    inc=by_date(data.get("income")); bal=by_date(data.get("balance")); cf=by_date(data.get("cashflow"))
    saved=0
    for d,i in inc.items():
        b=bal.get(d,{}) ; cash=cf.get(d,{})
        fcf=num(cash.get("freeCashFlow"))
        if fcf is None:
            ocf=num(cash.get("operatingCashFlow")); capex=num(cash.get("capitalExpenditure"))
            if ocf is not None and capex is not None: fcf=ocf+capex if capex<0 else ocf-capex
        payload={"company_id":c["id"],"period_end":d,"period_type":"annual",
          "revenue":num(i.get("revenue")),"operating_income":num(i.get("operatingIncome")),
          "net_income":num(i.get("netIncome")),"eps_diluted":num(i.get("epsDiluted")),
          "free_cash_flow":fcf,"capex":num(cash.get("capitalExpenditure")),
          "cash":num(b.get("cashAndCashEquivalents") or b.get("cashAndShortTermInvestments")),
          "total_debt":num(b.get("totalDebt")),"source":"fmp"}
        db.table("financial_metrics").upsert(payload,on_conflict="company_id,period_end,period_type,source").execute(); saved+=1
    return saved

async def main():
    p=argparse.ArgumentParser(description="Bootstrap annual fundamentals using the configured FMP plan")
    p.add_argument("--all",action="store_true"); p.add_argument("--batch-size",type=int,default=25)
    p.add_argument("--offset",type=int,default=0); p.add_argument("--delay",type=float,default=.25)
    p.add_argument("--tickers",nargs="*"); a=p.parse_args()
    db=get_supabase(); provider=FMPProvider()
    q=db.table("companies").select("id,ticker").eq("is_sp500",True).order("ticker").execute().data or []
    if a.tickers:
        wanted={x.upper() for x in a.tickers}; q=[x for x in q if x["ticker"] in wanted]
    elif not a.all: q=q[a.offset:a.offset+a.batch_size]
    ok=rows=failed=0
    print(f"Fundamentals bootstrap: {len(q)} companies")
    for idx,c in enumerate(q):
        if idx and a.delay: time.sleep(a.delay)
        try:
            n=await ingest_company(db,provider,c); rows+=n; ok+=1; print(c["ticker"],"rows=",n)
        except Exception as e:
            failed+=1; print(c["ticker"],"unavailable:",e)
    print(f"Done companies_ok={ok} failed={failed} rows_saved={rows}")

if __name__=="__main__": asyncio.run(main())
