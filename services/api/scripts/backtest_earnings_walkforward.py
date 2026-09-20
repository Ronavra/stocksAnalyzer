import argparse, sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

def f(v):
    try:return float(v) if v is not None else None
    except:return None

def summarize(rows,key):
    vals=[x[key] for x in rows if x.get(key) is not None]
    if not vals:return None
    return len(vals),sum(v>0 for v in vals)/len(vals),median(vals),sum(vals)/len(vals)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--min-events",type=int,default=20); a=ap.parse_args()
    db=get_supabase()
    companies={x["id"]:x["ticker"] for x in (db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or [])}
    observations=[]
    for cid,ticker in companies.items():
        events=db.table("earnings_events").select("reported_date,surprise_percent,revenue_surprise_percent").eq("company_id",cid).order("reported_date").execute().data or []
        if not events: continue
        prices=[]; start=0
        while True:
            chunk=(db.table("price_features").select("feature_date,close,drawdown_60d,relative_momentum_20d")
                   .eq("company_id",cid).order("feature_date").range(start,start+999).execute().data or [])
            prices+=chunk
            if len(chunk)<1000:break
            start+=1000
        for e in events:
            d=str(e["reported_date"]); idx=next((i for i,x in enumerate(prices) if str(x["feature_date"])>d),None)
            if idx is None:continue
            entry=f(prices[idx].get("close"))
            if not entry:continue
            o={"ticker":ticker,"year":int(d[:4]),"eps":f(e.get("surprise_percent")),"rev":f(e.get("revenue_surprise_percent")),
               "drawdown":f(prices[idx].get("drawdown_60d")),"relmom":f(prices[idx].get("relative_momentum_20d"))}
            for h in (5,20,60):
                j=idx+h
                o[f"ret{h}"]=None if j>=len(prices) else f(prices[j].get("close"))/entry-1
            observations.append(o)

    groups={"All":lambda x:True,"EPS beat >0":lambda x:x["eps"] is not None and x["eps"]>0,
            "EPS beat >=5%":lambda x:x["eps"] is not None and x["eps"]>=5,
            "EPS miss":lambda x:x["eps"] is not None and x["eps"]<0,
            "Beat>=5% + pullback>=10%":lambda x:x["eps"] is not None and x["eps"]>=5 and x["drawdown"] is not None and x["drawdown"]<=-.10}
    print("Walk-forward descriptive event study (entry: first session after report)")
    for year in sorted(set(x["year"] for x in observations)):
        train=[x for x in observations if x["year"]<year]; test=[x for x in observations if x["year"]==year]
        if len(train)<a.min_events or len(test)<a.min_events:continue
        print(f"\nTEST YEAR {year} | prior events={len(train)} test events={len(test)}")
        for name,fn in groups.items():
            rows=[x for x in test if fn(x)]
            parts=[]
            for h in (5,20,60):
                s=summarize(rows,f"ret{h}")
                if s and s[0]>=max(5,a.min_events//4):
                    parts.append(f"{h}d n={s[0]} up={s[1]:.1%} med={s[2]:+.2%} mean={s[3]:+.2%}")
            if parts: print(f"{name:26} "+" | ".join(parts))
    print("\nCaveats: current constituent universe creates survivorship bias; earnings coverage is partial; results are descriptive and not calibrated probabilities.")

if __name__=="__main__":main()
