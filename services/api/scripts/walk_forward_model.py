import sys, math, statistics
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, accuracy_score

db=get_supabase()
FEATURES=["momentum_5d","momentum_20d","volatility_20d","volume_change_5d","range_pct","close_vs_sma20","volume_ratio_20d"]

def fetch(company_id):
    out=[]; start=0
    while True:
        b=(db.table("price_features").select("feature_date,forward_up_5d,"+",".join(FEATURES))
           .eq("company_id",company_id).not_.is_("forward_up_5d","null").order("feature_date")
           .range(start,start+999).execute().data or [])
        out+=b
        if len(b)<1000: break
        start+=1000
    return [r for r in out if all(r.get(k) is not None for k in FEATURES)]

companies=db.table("companies").select("id,ticker").execute().data or []
all_preds=[]
for c in companies:
    rows=fetch(c["id"]); preds=[]
    # Expanding-window: initial ~3 years, then predict non-overlapping 5-day blocks.
    min_train=750
    for start in range(min_train,len(rows),5):
        train=rows[:start]; test=rows[start:min(start+5,len(rows))]
        X=[[float(r[k]) for k in FEATURES] for r in train]; y=[int(r["forward_up_5d"]) for r in train]
        Xt=[[float(r[k]) for k in FEATURES] for r in test]; yt=[int(r["forward_up_5d"]) for r in test]
        model=Pipeline([("scale",StandardScaler()),("lr",LogisticRegression(C=0.25,max_iter=1000))])
        model.fit(X,y); ps=model.predict_proba(Xt)[:,1]
        preds += list(zip(yt,ps))
    if not preds: continue
    y=[a for a,_ in preds]; p=[b for _,b in preds]; base=sum(y)/len(y)
    baseline_brier=sum((base-v)**2 for v in y)/len(y)
    brier=brier_score_loss(y,p); acc=accuracy_score(y,[v>=0.5 for v in p])
    print(f"{c['ticker']} oos={len(y)} up={base:.1%} brier={brier:.4f} baseline_brier={baseline_brier:.4f} accuracy={acc:.1%}")
    all_preds += preds
if all_preds:
    y=[a for a,_ in all_preds]; p=[b for _,b in all_preds]; base=sum(y)/len(y)
    print(f"\nPOOLED oos={len(y)} up={base:.1%} brier={brier_score_loss(y,p):.4f} baseline_brier={sum((base-v)**2 for v in y)/len(y):.4f}")
    for lo,hi in [(0,.45),(.45,.55),(.55,.65),(.65,1.01)]:
        z=[(a,b) for a,b in all_preds if lo<=b<hi]
        if z: print(f"  p={lo:.0%}-{hi:.0%}: n={len(z)} predicted={statistics.mean(b for _,b in z):.1%} realized={statistics.mean(a for a,_ in z):.1%}")
