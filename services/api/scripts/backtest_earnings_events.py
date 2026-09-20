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

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--min-events",type=int,default=20); a=ap.parse_args()
    db=get_supabase()
    companies={x["id"]:x["ticker"] for x in (db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or [])}
    events=[]
    for i in range(0,len(companies),100):
        ids=list(companies)[i:i+100]
        events += db.table("earnings_events").select("company_id,reported_date,surprise_percent,revenue_surprise_percent,source").in_("company_id",ids).execute().data or []
    by_company=defaultdict(list)
    for e in events: by_company[e["company_id"]].append(e)
    observations=[]
    for cid,evs in by_company.items():
        prices=[]
        start=0
        while True:
            chunk=(db.table("price_features").select("feature_date,close,forward_return_5d")
                   .eq("company_id",cid).order("feature_date").range(start,start+999).execute().data or [])
            prices+=chunk
            if len(chunk)<1000: break
            start+=1000
        if not prices: continue
        for e in evs:
            d=str(e["reported_date"])
            # Conservative alignment: use first trading session strictly after report date,
            # avoiding accidental use of same-day close for after-hours releases.
            p=next((x for x in prices if str(x["feature_date"])>d and x.get("forward_return_5d") is not None),None)
            if not p: continue
            observations.append({"ticker":companies[cid],"date":d,"eps":f(e.get("surprise_percent")),
              "rev":f(e.get("revenue_surprise_percent")),"ret5":f(p["forward_return_5d"]),"source":e.get("source")})
    def stats(name,rows):
        vals=[x["ret5"] for x in rows if x["ret5"] is not None]
        if len(vals)<a.min_events:return
        up=sum(x>0 for x in vals)/len(vals)
        print(f"{name:28} n={len(vals):4} up={up:6.1%} median5d={median(vals):+7.2%} mean5d={sum(vals)/len(vals):+7.2%}")
    print("Event study: first trading session after earnings report -> forward 5d")
    stats("All earnings",observations)
    stats("EPS beat > 0", [x for x in observations if x["eps"] is not None and x["eps"]>0])
    stats("EPS beat >= 5%", [x for x in observations if x["eps"] is not None and x["eps"]>=5])
    stats("EPS miss < 0", [x for x in observations if x["eps"] is not None and x["eps"]<0])
    stats("EPS beat + revenue beat",[x for x in observations if x["eps"] is not None and x["eps"]>0 and x["rev"] is not None and x["rev"]>0])
    print("NOTE: current earnings coverage is partial and may be survivorship-biased. This is descriptive, not validated predictive performance.")

if __name__=="__main__": main()
