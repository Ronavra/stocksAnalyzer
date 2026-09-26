from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import mean
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, mean_absolute_error

PRICE_FEATURES=[
    "return_1d","momentum_5d","momentum_20d","volatility_20d","volume_change_5d",
    "range_pct","close_vs_sma20","volume_ratio_20d","market_momentum_5d",
    "market_momentum_20d","market_volatility_20d","relative_momentum_5d",
    "relative_momentum_20d","drawdown_20d","drawdown_60d",
    "distance_to_support_60d","rebound_potential_20d","rebound_potential_60d",
]
FUND_FEATURES=[
    "fund_revenue_growth_yoy","fund_eps_growth_yoy","fund_operating_margin",
    "fund_net_margin","fund_fcf_margin","fund_debt_to_fcf","fund_cash_to_debt",
    "fund_age_days",
]
FEATURES=PRICE_FEATURES+FUND_FEATURES
HORIZONS=(5,10,20)
MODEL_VERSION="calibrated-price-fund-v1"

@dataclass
class HorizonModel:
    horizon:int
    classifier:Any
    calibrator:Any
    regressor:Any
    diagnostics:dict

    def probability(self,x):
        raw=float(self.classifier.predict_proba(np.asarray([x],dtype=float))[0,1])
        return float(self.calibrator.predict_proba(np.asarray([[raw]],dtype=float))[0,1])

    def expected_return(self,x):
        return float(self.regressor.predict(np.asarray([x],dtype=float))[0])


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError,ValueError):
        return None


def _paged(query_factory,page_size=1000):
    rows=[]; start=0
    while True:
        chunk=query_factory(start,start+page_size-1).execute().data or []
        rows.extend(chunk)
        if len(chunk)<page_size:
            break
        start+=page_size
    return rows


def load_ttm_fundamentals(db):
    rows=_paged(lambda a,b: db.table("financial_metrics")
        .select("company_id,period_end,filed_date,revenue,operating_income,net_income,eps_diluted,free_cash_flow,cash,total_debt")
        .eq("period_type","ttm")
        .order("company_id").order("filed_date").range(a,b))
    by_company={}
    for r in rows:
        if not r.get("filed_date"):
            continue
        by_company.setdefault(r["company_id"],[]).append(r)

    snapshots={}
    for cid,items in by_company.items():
        items=sorted(items,key=lambda x:(x["filed_date"],x["period_end"]))
        built=[]
        for i,r in enumerate(items):
            prior=None
            cur_end=date.fromisoformat(r["period_end"])
            for q in reversed(items[:i]):
                gap=(cur_end-date.fromisoformat(q["period_end"])).days
                if 300<=gap<=450:
                    prior=q; break
            revenue=_num(r.get("revenue")); eps=_num(r.get("eps_diluted"))
            op=_num(r.get("operating_income")); net=_num(r.get("net_income")); fcf=_num(r.get("free_cash_flow"))
            debt=_num(r.get("total_debt")); cash=_num(r.get("cash"))
            prev_rev=_num(prior.get("revenue")) if prior else None
            prev_eps=_num(prior.get("eps_diluted")) if prior else None
            vals={
                "fund_revenue_growth_yoy":(revenue/prev_rev-1) if revenue is not None and prev_rev not in (None,0) else None,
                "fund_eps_growth_yoy":(eps/abs(prev_eps)-1) if eps is not None and prev_eps not in (None,0) else None,
                "fund_operating_margin":op/revenue if op is not None and revenue not in (None,0) else None,
                "fund_net_margin":net/revenue if net is not None and revenue not in (None,0) else None,
                "fund_fcf_margin":fcf/revenue if fcf is not None and revenue not in (None,0) else None,
                "fund_debt_to_fcf":debt/abs(fcf) if debt is not None and fcf not in (None,0) else None,
                "fund_cash_to_debt":cash/debt if cash is not None and debt not in (None,0) else None,
            }
            built.append({"filed_date":r["filed_date"],"values":vals})
        snapshots[cid]=built
    return snapshots


def fundamental_asof(snapshots,cid,asof):
    items=snapshots.get(cid) or []
    if not items:
        return {k:None for k in FUND_FEATURES}
    keys=[x["filed_date"] for x in items]
    i=bisect_right(keys,asof)-1
    if i<0:
        return {k:None for k in FUND_FEATURES}
    item=items[i]
    out=dict(item["values"])
    out["fund_age_days"]=(date.fromisoformat(asof)-date.fromisoformat(item["filed_date"])).days
    return out


def _vector(row,fund):
    vals=[]
    for k in PRICE_FEATURES:
        v=_num(row.get(k)); vals.append(np.nan if v is None else v)
    for k in FUND_FEATURES:
        v=_num(fund.get(k)); vals.append(np.nan if v is None else v)
    return vals


def load_price_rows(db,years=5):
    latest=(db.table("price_features").select("feature_date").order("feature_date",desc=True).limit(1).execute().data or [])
    if not latest:
        return [],None
    latest_date=date.fromisoformat(latest[0]["feature_date"])
    cutoff=(latest_date-timedelta(days=365*years+45)).isoformat()
    cols="company_id,feature_date,"+",".join(PRICE_FEATURES)+",forward_return_5d,forward_return_10d,forward_return_20d"
    rows=_paged(lambda a,b: db.table("price_features").select(cols)
        .gte("feature_date",cutoff).order("feature_date").order("company_id").range(a,b))
    return rows,latest_date.isoformat()


def _classifier():
    return HistGradientBoostingClassifier(
        max_depth=3,max_iter=90,learning_rate=.05,l2_regularization=2.0,
        min_samples_leaf=40,random_state=42
    )


def _regressor():
    return HistGradientBoostingRegressor(
        max_depth=3,max_iter=90,learning_rate=.05,l2_regularization=2.0,
        min_samples_leaf=40,random_state=42
    )


def fit_models(db,years=5,min_rows=5000):
    price_rows,latest_date=load_price_rows(db,years)
    if not price_rows:
        return {},{"error":"no price features"}
    fund=load_ttm_fundamentals(db)
    all_dates=sorted({r["feature_date"] for r in price_rows})
    date_index={d:i for i,d in enumerate(all_dates)}
    # Use one cross-sectional anchor every five trading sessions to reduce
    # overlapping-label dependence while preserving several years of history.
    sampled_dates={d for i,d in enumerate(all_dates) if i%5==0}

    enriched=[]
    for r in price_rows:
        if r["feature_date"] not in sampled_dates:
            continue
        fr=fundamental_asof(fund,r["company_id"],r["feature_date"])
        enriched.append((r,_vector(r,fr)))

    models={}
    for h in HORIZONS:
        label=f"forward_return_{h}d"
        data=[(r,x,_num(r.get(label))) for r,x in enriched if r.get(label) is not None]
        if len(data)<min_rows:
            continue
        data.sort(key=lambda z:z[0]["feature_date"])
        dates=sorted({r["feature_date"] for r,_,_ in data})
        if len(dates)<120:
            continue

        # Expanding-window walk-forward OOF blocks. Each fold purges h trading
        # sessions before validation so its training labels were knowable then.
        fold_starts=[int(len(dates)*p) for p in (.58,.70,.82)]
        raw_oof=[]; y_oof=[]
        for fi,start in enumerate(fold_starts):
            end=fold_starts[fi+1] if fi+1<len(fold_starts) else len(dates)
            if start>=end:
                continue
            val_dates=set(dates[start:end])
            val_start=dates[start]
            full_i=date_index[val_start]
            purge_i=max(0,full_i-h)
            cutoff=all_dates[purge_i]
            train=[z for z in data if z[0]["feature_date"]<cutoff]
            valid=[z for z in data if z[0]["feature_date"] in val_dates]
            if len(train)<min_rows//2 or len(valid)<500:
                continue
            Xtr=np.asarray([z[1] for z in train],dtype=float)
            ytr=np.asarray([z[2]>0 for z in train],dtype=int)
            Xv=np.asarray([z[1] for z in valid],dtype=float)
            yv=np.asarray([z[2]>0 for z in valid],dtype=int)
            clf=_classifier(); clf.fit(Xtr,ytr)
            raw=clf.predict_proba(Xv)[:,1]
            raw_oof.extend(raw.tolist()); y_oof.extend(yv.tolist())

        if len(raw_oof)<1000 or len(set(y_oof))<2:
            continue
        raw_arr=np.asarray(raw_oof,dtype=float)
        y_arr=np.asarray(y_oof,dtype=int)
        calibrator=LogisticRegression(C=1.0,solver="lbfgs")
        calibrator.fit(raw_arr.reshape(-1,1),y_arr)
        cal=calibrator.predict_proba(raw_arr.reshape(-1,1))[:,1]
        base=np.full_like(cal,float(y_arr.mean()),dtype=float)

        X=np.asarray([z[1] for z in data],dtype=float)
        y_cls=np.asarray([z[2]>0 for z in data],dtype=int)
        y_ret=np.asarray([z[2] for z in data],dtype=float)
        clf=_classifier(); clf.fit(X,y_cls)
        reg=_regressor(); reg.fit(X,y_ret)
        pred_ret=reg.predict(X[-min(10000,len(X)):])
        actual_ret=y_ret[-len(pred_ret):]

        diagnostics={
            "model_version":MODEL_VERSION,
            "horizon_days":h,
            "training_rows":len(data),
            "training_dates":len(dates),
            "oof_rows":len(y_oof),
            "oof_up_rate":float(y_arr.mean()),
            "raw_brier":float(brier_score_loss(y_arr,raw_arr)),
            "calibrated_brier":float(brier_score_loss(y_arr,cal)),
            "baseline_brier":float(brier_score_loss(y_arr,base)),
            "calibration_beats_baseline":bool(brier_score_loss(y_arr,cal)<brier_score_loss(y_arr,base)),
            "recent_train_mae":float(mean_absolute_error(actual_ret,pred_ret)),
            "price_feature_count":len(PRICE_FEATURES),
            "fundamental_feature_count":len(FUND_FEATURES),
        }
        models[h]=HorizonModel(h,clf,calibrator,reg,diagnostics)
    return models,{"latest_feature_date":latest_date,"features":FEATURES,"fundamental_companies":len(fund)}


def current_feature_rows(db):
    latest=(db.table("price_features").select("feature_date").order("feature_date",desc=True).limit(1).execute().data or [])
    if not latest:
        return {},None
    d=latest[0]["feature_date"]
    cols="company_id,feature_date,"+",".join(PRICE_FEATURES)
    rows=(db.table("price_features").select(cols).eq("feature_date",d).execute().data or [])
    return {r["company_id"]:r for r in rows},d


def predict_current(db,models):
    rows,d=current_feature_rows(db)
    fund=load_ttm_fundamentals(db)
    out={}
    for cid,r in rows.items():
        fr=fundamental_asof(fund,cid,d)
        x=_vector(r,fr)
        present=sum(not np.isnan(v) for v in x)/len(x)
        out[cid]={}
        for h,m in models.items():
            out[cid][h]={
                "probability_up":m.probability(x),
                "expected_return":m.expected_return(x),
                "feature_coverage":present,
                "diagnostics":m.diagnostics,
            }
    return out,d
