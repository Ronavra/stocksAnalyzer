import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.research.signal_execution import execution_update
from app.research.price_window import canonical_prices

def main():
    db=get_supabase()
    pending=[]
    for offset in range(0,1000000,1000):
        page=(db.table("research_predictions")
              .select("id,company_id,signal_date,horizon_days,entry_price,model_diagnostics")
              .is_("evaluated_at","null").order("id").range(offset,offset+999).execute().data or [])
        pending.extend(page)
        if len(page)<1000: break
    spy=(db.table("companies").select("id").eq("ticker","SPY").limit(1).execute().data or [])
    spy_id=spy[0]["id"] if spy else None
    done=0
    for p in pending:
        delayed=(p.get("model_diagnostics") or {}).get("entry_policy")=="next_session_close"
        def series(company_id):
            rows=[]
            for offset in range(0,1000000,1000):
                page=(db.table("price_history").select("price_date,close,source")
                      .eq("company_id",company_id).gt("price_date",p["signal_date"])
                      .order("price_date").order("source").range(offset,offset+999).execute().data or [])
                rows.extend(page)
                if len(page)<1000: break
            return canonical_prices(rows)
        prices=series(p["company_id"])
        calendar=None
        if delayed:
            if not spy_id: continue
            calendar=[r["price_date"] for r in series(spy_id)]
        update,entry_date=execution_update(p,prices,calendar)
        if entry_date is None:
            if update:
                db.table("research_predictions").update(update).eq("id",p["id"]).execute()
            continue
        benchmark=None
        if spy_id:
            q=db.table("price_history").select("close").eq("company_id",spy_id)
            q=q.eq("price_date",entry_date) if delayed else q.lte("price_date",entry_date)
            s0=(q.order("price_date",desc=True).order("source",desc=True).limit(1).execute().data or [])
            s1=(db.table("price_history").select("close").eq("company_id",spy_id).eq("price_date",update["exit_date"]).order("source",desc=True).limit(1).execute().data or [])
            if s0 and s1: benchmark=float(s1[0]["close"])/float(s0[0]["close"])-1
        if spy_id and benchmark is None:
            # Keep it pending until the same-date benchmark is available.
            continue
        update.update({"evaluated_at":date.today().isoformat(),"benchmark_return":benchmark,
                       "excess_return":None if benchmark is None else update["actual_return"]-benchmark})
        db.table("research_predictions").update(update).eq("id",p["id"]).execute()
        done+=1
    print(f"Evaluated {done} matured signals; {len(pending)-done} remain pending")

if __name__=="__main__": main()
