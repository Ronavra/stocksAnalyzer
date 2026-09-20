import argparse, sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

def f(v):
    try: return float(v) if v is not None else None
    except: return None

def generate(db, top=5, horizon=5):
    rows=db.rpc("research_dashboard_candidates").execute().data or []
    ids=[r.get("company_id") for r in rows if r.get("company_id")]
    earnings={}
    if ids:
        ev=(db.table("earnings_events").select("company_id,reported_date,surprise_percent,revenue_surprise_percent,source")
            .in_("company_id",ids).eq("source","massive_benzinga").lte("reported_date",date.today().isoformat())
            .order("reported_date",desc=True).execute().data or [])
        for e in ev: earnings.setdefault(e["company_id"],e)
    picks=[]
    for r in rows:
        score=f(r.get("opportunity_score")); up=f(r.get("setup_probability_up")); med=f(r.get("setup_median_return_5d")); n=int(r.get("setup_sample_size") or 0)
        price=f(r.get("current_price"))
        if None in (score,up,med,price) or n<50: continue
        e=earnings.get(r.get("company_id")) or {}
        vals=[f(e.get("surprise_percent")),f(e.get("revenue_surprise_percent"))]; vals=[x for x in vals if x is not None]
        adj=max(-8,min(8,sum(max(-20,min(20,x)) for x in vals)/5)) if vals else 0
        rank_score=score+adj
        # Production v1 gate: positive historical setup evidence and adequate sample size.
        if up<0.52 or med<=0: continue
        picks.append((rank_score,r,e))
    picks.sort(key=lambda x:x[0],reverse=True)
    today=date.today().isoformat()
    out=[]
    for rank,(rank_score,r,e) in enumerate(picks[:top],1):
        rec={"company_id":r["company_id"],"signal_date":r.get("price_date") or r.get("as_of_date") or today,"horizon_days":horizon,"signal":"UP","rank":rank,
             "entry_price":r.get("current_price"),"research_score":round(rank_score,2),
             "historical_up_rate":r.get("setup_probability_up"),"historical_median_return":r.get("setup_median_return_5d"),
             "sample_size":r.get("setup_sample_size"),"catalyst":e or None,"model_version":"weekly-signal-v1"}
        db.table("research_predictions").upsert(rec,on_conflict="company_id,signal_date,horizon_days,model_version").execute()
        out.append((r.get("ticker"),rank_score,r.get("current_price")))
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--top",type=int,default=5); ap.add_argument("--horizon",type=int,choices=[5,10,20],default=5); a=ap.parse_args()
    picks=generate(get_supabase(),a.top,a.horizon)
    print(f"Saved {len(picks)} frozen UP signals")
    for i,(ticker,score,price) in enumerate(picks,1): print(f"{i}. {ticker} research_score={score:.1f} entry={price}")

if __name__=="__main__": main()
