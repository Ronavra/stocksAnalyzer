import sys, statistics
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
for c in companies:
 rows=fetch(c["id"])
 if not rows: continue
 cur=rows[-1]; dd=cur.get("drawdown_60d"); ds=cur.get("distance_to_support_60d")
 matches=[r for r in rows[:-5] if r.get("forward_return_5d") is not None and r.get("drawdown_60d") is not None and r.get("distance_to_support_60d") is not None and dd is not None and ds is not None and abs(float(r["drawdown_60d"])-float(dd))<=.04 and abs(float(r["distance_to_support_60d"])-float(ds))<=.04]
 rets=[float(r["forward_return_5d"]) for r in matches]
 up=sum(x>0 for x in rets)/len(rets) if rets else None; med=statistics.median(rets) if rets else None; upside=cur.get("rebound_potential_60d")
 print(c["ticker"],"drawdown=",f"{float(dd):.1%}" if dd is not None else "n/a","support_distance=",f"{float(ds):.1%}" if ds is not None else "n/a","upside_to_60d_high=",f"{float(upside):.1%}" if upside is not None else "n/a","similar_n=",len(rets),"historical_up=",f"{up:.1%}" if up is not None else "n/a","median_5d=",f"{med:.1%}" if med is not None else "n/a")
