import asyncio,sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.fmp import FMPProvider
from app.research.valuation import derive,score

async def main():
    db=get_supabase(); provider=FMPProvider(); today=str(date.today())
    companies=db.table("companies").select("id,ticker,scoring_profile").execute().data or []
    for c in companies:
        if c.get("scoring_profile")=="bank":
            print(c["ticker"],"bank valuation model pending"); continue
        try:
            quote_result=await provider.quote(c["ticker"])
            quote=quote_result.value[0] if isinstance(quote_result.value,list) and quote_result.value else quote_result.value
            rows=(db.table("financial_metrics").select("*").eq("company_id",c["id"])
                  .eq("period_type","annual").order("period_end",desc=True).limit(1).execute().data or [])
            if not rows: continue
            signals=derive(quote or {},rows[0]); value,coverage=score(signals)
            db.table("valuation_snapshots").upsert({
              "company_id":c["id"],"snapshot_date":today,"pe":signals.pe,
              "price_to_fcf":signals.price_to_fcf,"fcf_yield":signals.fcf_yield,
              "market_cap":signals.market_cap,"source":"fmp"
            },on_conflict="company_id,snapshot_date,source").execute()
            db.table("research_snapshots").upsert({
              "company_id":c["id"],"as_of_date":today,"valuation_score":value,
              "valuation_coverage":coverage,"pe":signals.pe,"price_to_fcf":signals.price_to_fcf,
              "fcf_yield":signals.fcf_yield,"market_cap":signals.market_cap
            },on_conflict="company_id,as_of_date").execute()
            print(c["ticker"],"valuation_score=",value,f"coverage={coverage}%","PE=",None if signals.pe is None else round(signals.pe,2),"P/FCF=",None if signals.price_to_fcf is None else round(signals.price_to_fcf,2))
        except Exception as exc:
            print("FAILED",c["ticker"],exc)
if __name__=="__main__": asyncio.run(main())
