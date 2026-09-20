import sys, statistics
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

db=get_supabase()
TOPS=(5,10,20)
MIN_HISTORY=120
STEP=5

def fetch(cid):
 rows=[]; start=0
 while True:
  b=(db.table("price_features")
     .select("feature_date,forward_return_5d,drawdown_60d,distance_to_support_60d,rebound_potential_60d")
     .eq("company_id",cid).order("feature_date").range(start,start+999).execute().data or [])
  rows.extend(b)
  if len(b)<1000: break
  start+=1000
 return rows

def score_at(rows,i):
 cur=rows[i]; dd=cur.get("drawdown_60d"); ds=cur.get("distance_to_support_60d")
 if dd is None or ds is None: return None
 # Purge: at anchor i, a 5-day forward label is only known through i-5.
 hist=rows[:max(0,i-4)]
 matches=[r for r in hist if r.get("forward_return_5d") is not None
          and r.get("drawdown_60d") is not None and r.get("distance_to_support_60d") is not None
          and abs(float(r["drawdown_60d"])-float(dd))<=.04
          and abs(float(r["distance_to_support_60d"])-float(ds))<=.04]
 rets=[float(r["forward_return_5d"]) for r in matches]
 n=len(rets)
 if not n: return None
 up=sum(x>0 for x in rets)/n
 med=statistics.median(rets)
 upside=float(cur["rebound_potential_60d"]) if cur.get("rebound_potential_60d") is not None else 0
 shrunk=(sum(x>0 for x in rets)+10)/(n+20)
 pc=max(0,min(1,(shrunk-.45)/.25))
 rc=max(0,min(1,(med+.01)/.05))
 uc=max(0,min(1,upside/.20))
 evidence=min(1,n/100)
 score=100*(.50*pc+.30*rc+.20*uc)*(.65+.35*evidence)
 return score,n

companies=(db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or [])
series={c["ticker"]:fetch(c["id"]) for c in companies}
by_date=defaultdict(list)
for ticker,rows in series.items():
 for i in range(MIN_HISTORY,len(rows)-5,STEP):
  fwd=rows[i].get("forward_return_5d")
  if fwd is None: continue
  s=score_at(rows,i)
  if s is not None: by_date[rows[i]["feature_date"]].append((s[0],ticker,float(fwd),s[1]))

results={k:[] for k in TOPS}; universe=[]
for d,items in sorted(by_date.items()):
 if len(items)<20: continue
 ranked=sorted(items,reverse=True)
 universe.extend(x[2] for x in items)
 for k in TOPS:
  chosen=ranked[:k]
  results[k].extend(x[2] for x in chosen)

print(f"weekly anchors evaluated={len(by_date)} companies={len(series)}")
base_up=sum(x>0 for x in universe)/len(universe); base_med=statistics.median(universe)
print(f"Universe: n={len(universe)} up={base_up:.1%} median_5d={base_med:.2%}")
for k in TOPS:
 vals=results[k]
 up=sum(x>0 for x in vals)/len(vals)
 med=statistics.median(vals)
 mean=statistics.mean(vals)
 q=statistics.quantiles(vals,n=10)
 print(f"Top {k}: n={len(vals)} up={up:.1%} median_5d={med:.2%} mean_5d={mean:.2%} p10={q[0]:.2%} p90={q[8]:.2%} lift_up={(up-base_up):+.1%} lift_median={(med-base_med):+.2%}")
