import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

def main():
    db=get_supabase()
    pending=db.table("research_predictions").select("id,company_id,signal_date,horizon_days,entry_price").is_("evaluated_at","null").execute().data or []
    spy=(db.table("companies").select("id").eq("ticker","SPY").limit(1).execute().data or [])
    spy_id=spy[0]["id"] if spy else None
    done=0
    for p in pending:
        prices=(db.table("price_history").select("price_date,close").eq("company_id",p["company_id"]).gt("price_date",p["signal_date"]).order("price_date").limit(p["horizon_days"]).execute().data or [])
        if len(prices)<p["horizon_days"]: continue
        exit_row=prices[p["horizon_days"]-1]; entry=float(p["entry_price"]); exit_price=float(exit_row["close"]); actual=exit_price/entry-1
        benchmark=None
        if spy_id:
            s0=(db.table("price_history").select("close").eq("company_id",spy_id).lte("price_date",p["signal_date"]).order("price_date",desc=True).limit(1).execute().data or [])
            s1=(db.table("price_history").select("close").eq("company_id",spy_id).eq("price_date",exit_row["price_date"]).limit(1).execute().data or [])
            if s0 and s1: benchmark=float(s1[0]["close"])/float(s0[0]["close"])-1
        db.table("research_predictions").update({"evaluated_at":date.today().isoformat(),"exit_date":exit_row["price_date"],"exit_price":exit_price,
          "actual_return":actual,"benchmark_return":benchmark,"excess_return":None if benchmark is None else actual-benchmark,"correct_direction":actual>0}).eq("id",p["id"]).execute()
        done+=1
    print(f"Evaluated {done} matured signals; {len(pending)-done} remain pending")

if __name__=="__main__": main()
