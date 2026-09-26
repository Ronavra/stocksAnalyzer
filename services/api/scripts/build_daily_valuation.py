import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase

SOURCE="sec_price_derived"

def num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError,ValueError):
        return None

def paged(query_factory,page_size=1000):
    rows=[]; start=0
    while True:
        chunk=query_factory(start,start+page_size-1).execute().data or []
        rows.extend(chunk)
        if len(chunk)<page_size:
            break
        start+=page_size
    return rows

def main():
    db=get_supabase()
    latest=(db.table("price_history").select("price_date").order("price_date",desc=True).limit(1).execute().data or [])
    if not latest:
        raise RuntimeError("No price history available")
    snapshot_date=latest[0]["price_date"]

    prices=(db.table("price_history").select("company_id,close")
            .eq("price_date",snapshot_date).execute().data or [])
    price_by_company={}
    for r in prices:
        price_by_company.setdefault(r["company_id"],num(r.get("close")))

    metrics=paged(lambda a,b: db.table("financial_metrics")
        .select("company_id,period_end,filed_date,eps_diluted,free_cash_flow,shares_outstanding")
        .eq("period_type","ttm").lte("filed_date",snapshot_date)
        .order("company_id").order("filed_date",desc=True).range(a,b))
    latest_ttm={}
    for r in metrics:
        latest_ttm.setdefault(r["company_id"],r)

    payload=[]
    for cid,price in price_by_company.items():
        m=latest_ttm.get(cid)
        if not m or price in (None,0):
            continue
        eps=num(m.get("eps_diluted")); fcf=num(m.get("free_cash_flow")); shares=num(m.get("shares_outstanding"))
        pe=price/eps if eps is not None and eps>0 else None
        market_cap=price*shares if shares is not None and shares>0 else None
        price_to_fcf=market_cap/fcf if market_cap is not None and fcf is not None and fcf>0 else None
        fcf_yield=fcf/market_cap if market_cap not in (None,0) and fcf is not None else None
        if all(x is None for x in (pe,market_cap,price_to_fcf,fcf_yield)):
            continue
        payload.append({
            "company_id":cid,"snapshot_date":snapshot_date,"pe":pe,
            "price_to_fcf":price_to_fcf,"fcf_yield":fcf_yield,
            "market_cap":market_cap,"source":SOURCE,
        })

    for i in range(0,len(payload),250):
        db.table("valuation_snapshots").upsert(
            payload[i:i+250],
            on_conflict="company_id,snapshot_date,source"
        ).execute()
    print(f"Built {len(payload)} internal valuation snapshots for {snapshot_date} from SEC TTM + latest close")

if __name__=="__main__":
    main()
