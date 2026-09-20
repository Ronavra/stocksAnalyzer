import sys, statistics, math
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
db=get_supabase()
companies=(db.table("companies").select("id,ticker").neq("scoring_profile","benchmark").execute().data or [])

def fetch(cid):
 rows=[]; start=0
 while True:
  b=(db.table("price_features").select("*").eq("company_id",cid).order("feature_date").range(start,start+999).execute().data or [])
  rows.extend(b)
  if len(b)<1000: break
  start+=1000
 return rows

ranked=[]
for c in companies:
 rows=fetch(c["id"])
 if not rows: continue
 cur=rows[-1]; dd=cur.get("drawdown_60d"); ds=cur.get("distance_to_support_60d")
 matches=[r for r in rows[:-5] if r.get("forward_return_5d") is not None and r.get("drawdown_60d") is not None and r.get("distance_to_support_60d") is not None and dd is not None and ds is not None and abs(float(r["drawdown_60d"])-float(dd))<=.04 and abs(float(r["distance_to_support_60d"])-float(ds))<=.04]
 rets=[float(r["forward_return_5d"]) for r in matches]
 n=len(rets); up=sum(x>0 for x in rets)/n if n else None
 med=statistics.median(rets) if rets else None
 upside=float(cur["rebound_potential_60d"]) if cur.get("rebound_potential_60d") is not None else None
 # Empirical opportunity score: shrunk setup hit-rate + observed median return + recovery room.
 # Shrink small samples toward 50%; cap recovery room so a crash alone cannot dominate.
 shrunk=((sum(x>0 for x in rets)+10)/(n+20)) if n else None
 prob_component=max(0,min(1,(shrunk-.45)/.25)) if shrunk is not None else 0
 return_component=max(0,min(1,(med+.01)/.05)) if med is not None else 0
 upside_component=max(0,min(1,(upside or 0)/.20))
 evidence=min(1,n/100)
 score=100*(.50*prob_component+.30*return_component+.20*upside_component)*(.65+.35*evidence) if n else None
 reason=(f"{n} similar setups; {up:.1%} positive; median 5d {med:.1%}; {upside:.1%} room to 60d high" if n and upside is not None else "Insufficient comparable setup history")
 snapshot_date=cur["feature_date"]
 values={"company_id":c["id"],"as_of_date":snapshot_date,
         "opportunity_score":round(score,2) if score is not None else None,
         "setup_probability_up":up,"setup_median_return_5d":med,"setup_sample_size":n,
         "upside_to_60d_high":upside,"setup_drawdown_60d":float(dd) if dd is not None else None,
         "opportunity_reason":reason}
 # Every company with price features gets a snapshot, even when fundamentals
 # have not been ingested yet. This lets the API rank the full S&P 500 universe.
 db.table("research_snapshots").upsert(values,on_conflict="company_id,as_of_date").execute()
 ranked.append((score or -1,c["ticker"],n,up,med,upside,dd))
for i,x in enumerate(sorted(ranked,reverse=True),1):
 score,t,n,up,med,upside,dd=x
 print(f"{i:>2}. {t:<5} opportunity={score:.1f}" if score>=0 else f"{i:>2}. {t:<5} opportunity=n/a",
       f"historical_up={up:.1%}" if up is not None else "historical_up=n/a",
       f"median_5d={med:.1%}" if med is not None else "median_5d=n/a",
       f"upside_to_60d_high={upside:.1%}" if upside is not None else "upside=n/a",
       f"n={n}")
