import sys, statistics, math
from collections import defaultdict
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
db=get_supabase()

TOPS=(5,10,20); MIN_HISTORY=120; STEP=5

def fetch(cid):
 rows=[]; start=0
 while True:
  b=(db.table("price_features")
    .select("feature_date,close,return_1d,momentum_5d,momentum_20d,volatility_20d,volume_ratio_20d,close_vs_sma20,relative_momentum_5d,relative_momentum_20d,drawdown_20d,drawdown_60d,distance_to_support_60d,rebound_potential_60d,forward_return_5d")
    .eq("company_id",cid).order("feature_date").range(start,start+999).execute().data or [])
  rows.extend(b)
  if len(b)<1000: break
  start+=1000
 return rows

def f(x): return float(x) if x is not None else None
def clamp(x,a=0,b=1): return max(a,min(b,x))

def setup_score(r):
 # v2 is intentionally interpretable: pullback + proximity to support +
 # stabilization/reversal + relative strength. No future-return matching.
 dd=f(r.get("drawdown_60d")); support=f(r.get("distance_to_support_60d"))
 r1=f(r.get("return_1d")); m5=f(r.get("momentum_5d")); m20=f(r.get("momentum_20d"))
 rel5=f(r.get("relative_momentum_5d")); sma=f(r.get("close_vs_sma20"))
 volratio=f(r.get("volume_ratio_20d"))
 if dd is None or support is None or m5 is None or rel5 is None: return None
 # Prefer meaningful pullbacks (~5-25%), not fresh highs or catastrophic collapses.
 depth=clamp(((-dd)-.04)/.16) * clamp((.35-(-dd))/.15)
 # Near the rolling support zone; fades as price gets far above the recent low.
 near_support=1-clamp(support/.18)
 # Reversal: short momentum/last day improve while medium-term price is still depressed.
 reversal=.5*clamp(((r1 or 0)+.02)/.04)+.5*clamp((m5+.04)/.08)
 # Relative stabilization versus SPY is more useful than absolute bounce alone.
 relative=clamp((rel5+.04)/.08)
 # Below/near SMA20 leaves recovery room, but penalize extreme breakdowns.
 structure=1-clamp(abs((sma or 0)+.03)/.15)
 # Volume confirmation gets a small capped contribution.
 volume=clamp(((volratio or 1)-.7)/.8)
 return 100*(.25*depth+.25*near_support+.20*reversal+.20*relative+.07*structure+.03*volume)

companies=(db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or [])
series={c["ticker"]:fetch(c["id"]) for c in companies}
by_date=defaultdict(list)
for ticker,rows in series.items():
 for i in range(MIN_HISTORY,len(rows)-5,STEP):
  fwd=f(rows[i].get("forward_return_5d"))
  if fwd is None: continue
  s=setup_score(rows[i])
  if s is not None: by_date[rows[i]["feature_date"]].append((s,ticker,fwd))

results={k:[] for k in TOPS}; universe=[]
for d,items in sorted(by_date.items()):
 if len(items)<20: continue
 ranked=sorted(items,reverse=True)
 universe.extend(x[2] for x in items)
 for k in TOPS: results[k].extend(x[2] for x in ranked[:k])

base_up=sum(x>0 for x in universe)/len(universe); base_med=statistics.median(universe)
print(f"Setup v2 weekly anchors={len(by_date)} companies={len(series)}")
print(f"Universe: n={len(universe)} up={base_up:.1%} median_5d={base_med:.2%}")
for k in TOPS:
 vals=results[k]; up=sum(x>0 for x in vals)/len(vals); med=statistics.median(vals); mean=statistics.mean(vals)
 q=statistics.quantiles(vals,n=10)
 print(f"Top {k}: n={len(vals)} up={up:.1%} median_5d={med:.2%} mean_5d={mean:.2%} p10={q[0]:.2%} p90={q[8]:.2%} lift_up={(up-base_up):+.1%} lift_median={(med-base_med):+.2%}")
