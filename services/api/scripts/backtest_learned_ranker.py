import sys, statistics, numpy as np
from pathlib import Path
from dotenv import load_dotenv
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
db=get_supabase()

FEATURES=["momentum_5d","momentum_20d","volatility_20d","volume_ratio_20d","close_vs_sma20",
"relative_momentum_5d","relative_momentum_20d","drawdown_20d","drawdown_60d",
"distance_to_support_60d","rebound_potential_20d","rebound_potential_60d",
"market_momentum_5d","market_momentum_20d","market_volatility_20d"]
TOPS=(5,10,20); MIN_TRAIN_DAYS=500; RETRAIN_EVERY=20

def fetch(cid):
 rows=[]; s=0
 cols="feature_date,forward_return_5d,"+",".join(FEATURES)
 while True:
  b=(db.table("price_features").select(cols).eq("company_id",cid).order("feature_date").range(s,s+999).execute().data or [])
  rows+=b
  if len(b)<1000: break
  s+=1000
 return rows

companies=(db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or [])
data={}
dates=set()
for c in companies:
 rows=fetch(c["id"]); data[c["ticker"]]={r["feature_date"]:r for r in rows}; dates.update(r["feature_date"] for r in rows)
dates=sorted(dates)
model=Pipeline([("imp",SimpleImputer(strategy="median")),("m",HistGradientBoostingRegressor(max_depth=3,learning_rate=.05,max_iter=120,l2_regularization=2.0,random_state=42))])
results={k:[] for k in TOPS}; universe=[]; fitted=False; anchors=0

for di in range(MIN_TRAIN_DAYS,len(dates)-5,5):
 d=dates[di]
 # Purge 5 trading dates: labels after this cutoff were not knowable at anchor.
 cutoff=dates[di-5]
 if (not fitted) or anchors%RETRAIN_EVERY==0:
  X=[]; y=[]
  for ticker,byd in data.items():
   for td,r in byd.items():
    if td>cutoff: continue
    target=r.get("forward_return_5d")
    if target is None: continue
    X.append([float(r[x]) if r.get(x) is not None else np.nan for x in FEATURES]); y.append(float(target))
  if len(y)<1000: continue
  model.fit(np.asarray(X),np.asarray(y)); fitted=True
 items=[]
 for ticker,byd in data.items():
  r=byd.get(d)
  if not r or r.get("forward_return_5d") is None: continue
  x=np.asarray([[float(r[z]) if r.get(z) is not None else np.nan for z in FEATURES]])
  pred=float(model.predict(x)[0]); actual=float(r["forward_return_5d"])
  items.append((pred,ticker,actual))
 if len(items)<20: continue
 anchors+=1; items.sort(reverse=True); universe += [x[2] for x in items]
 for k in TOPS: results[k] += [x[2] for x in items[:k]]

base_up=sum(x>0 for x in universe)/len(universe); base_med=statistics.median(universe)
print(f"Learned ranker anchors={anchors} companies={len(companies)} features={len(FEATURES)}")
print(f"Universe: n={len(universe)} up={base_up:.1%} median_5d={base_med:.2%}")
for k in TOPS:
 v=results[k]; up=sum(x>0 for x in v)/len(v); med=statistics.median(v); mean=statistics.mean(v); q=statistics.quantiles(v,n=10)
 print(f"Top {k}: n={len(v)} up={up:.1%} median_5d={med:.2%} mean_5d={mean:.2%} p10={q[0]:.2%} p90={q[8]:.2%} lift_up={(up-base_up):+.1%} lift_median={(med-base_med):+.2%}")
