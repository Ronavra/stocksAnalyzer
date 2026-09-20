import argparse, sys, math
from pathlib import Path
from statistics import median
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase

try:
    import numpy as np
    from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
    from sklearn.metrics import brier_score_loss
except ImportError:
    raise SystemExit("Install model deps: pip install scikit-learn numpy")

FEATURES=["eps_surprise","revenue_surprise","drawdown_60d","relative_momentum_20d","momentum_20d","volatility_20d","market_momentum_20d","market_volatility_20d"]

def num(v):
    try:return float(v) if v is not None else math.nan
    except:return math.nan

def load_rows(db):
    companies=db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or []
    out=[]
    for c in companies:
        events=db.table("earnings_events").select("reported_date,event_time,surprise_percent,revenue_surprise_percent,source").eq("company_id",c["id"]).order("reported_date").execute().data or []
        events=[e for e in events if e.get("source")=="massive_benzinga"]
        if not events: continue
        pf=[]; start=0
        while True:
            chunk=(db.table("price_features").select("feature_date,close,drawdown_60d,relative_momentum_20d,momentum_20d,volatility_20d,market_momentum_20d,market_volatility_20d")
                   .eq("company_id",c["id"]).order("feature_date").range(start,start+999).execute().data or [])
            pf+=chunk
            if len(chunk)<1000: break
            start+=1000
        for e in events:
            d=str(e["reported_date"])
            t=str(e.get("event_time") or "")
            premarket=bool(t and t < "09:30:00")
            i=next((i for i,x in enumerate(pf) if str(x["feature_date"])>=d),None) if premarket else next((i for i,x in enumerate(pf) if str(x["feature_date"])>d),None)
            if i is None or i+5>=len(pf): continue
            feature_i=max(0,i-1)
            entry=num(pf[i]["close"]); future=num(pf[i+5]["close"])
            if math.isnan(entry) or math.isnan(future) or entry==0: continue
            ret=future/entry-1
            x={"eps_surprise":num(e.get("surprise_percent")),"revenue_surprise":num(e.get("revenue_surprise_percent"))}
            for k in FEATURES[2:]: x[k]=num(pf[feature_i].get(k))
            out.append({"ticker":c["ticker"],"year":int(d[:4]),"x":[x[k] for k in FEATURES],"ret":ret,"up":int(ret>0)})
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--min-train",type=int,default=300); ap.add_argument("--top",type=int,default=5); a=ap.parse_args()
    db=get_supabase(); rows=load_rows(db); years=sorted(set(r["year"] for r in rows)); all_test=[]
    print("True walk-forward earnings model | target: next 5 trading sessions")
    print("Features:",", ".join(FEATURES))
    for year in years:
        train=[r for r in rows if r["year"]<year]; test=[r for r in rows if r["year"]==year]
        if len(train)<a.min_train or len(test)<10: continue
        X=np.array([r["x"] for r in train],dtype=float); y=np.array([r["up"] for r in train]); yr=np.array([r["ret"] for r in train])
        Xt=np.array([r["x"] for r in test],dtype=float)
        clf=HistGradientBoostingClassifier(max_iter=120,max_leaf_nodes=12,l2_regularization=2.0,random_state=42).fit(X,y)
        reg=HistGradientBoostingRegressor(max_iter=120,max_leaf_nodes=12,l2_regularization=2.0,random_state=42).fit(X,yr)
        probs=clf.predict_proba(Xt)[:,1]; preds=reg.predict(Xt)
        for r,p,er in zip(test,probs,preds): r["prob"]=float(p); r["pred_ret"]=float(er)
        actual=np.array([r["up"] for r in test]); base=float(np.mean(y))
        brier=brier_score_loss(actual,probs); base_brier=brier_score_loss(actual,np.full(len(actual),base))
        ranked=sorted(test,key=lambda r:(r["prob"],r["pred_ret"]),reverse=True)[:a.top]
        vals=[r["ret"] for r in ranked]
        print(f"{year}: train={len(train)} test={len(test)} base_up={base:.1%} actual_up={np.mean(actual):.1%} brier={brier:.4f} base_brier={base_brier:.4f} top{len(vals)}_up={np.mean([v>0 for v in vals]):.1%} top_med={median(vals):+.2%}")
        all_test+=test
    if all_test:
        y=np.array([r["up"] for r in all_test]); p=np.array([r["prob"] for r in all_test])
        print(f"\nOOF total n={len(all_test)} up={np.mean(y):.1%} brier={brier_score_loss(y,p):.4f}")
        for lo,hi in [(0,.5),(.5,.6),(.6,.7),(.7,.8),(.8,1.01)]:
            bucket=[r for r in all_test if lo<=r["prob"]<hi]
            if bucket: print(f"prob {lo:.0%}-{hi:.0%}: n={len(bucket)} predicted={sum(r['prob'] for r in bucket)/len(bucket):.1%} actual={sum(r['up'] for r in bucket)/len(bucket):.1%}")
    print("\nCaveats: current-index survivorship bias remains; future-dated events are naturally excluded because no post-event price label exists. Do not use these probabilities in production until calibration and broader point-in-time coverage are validated.")

if __name__=="__main__": main()
