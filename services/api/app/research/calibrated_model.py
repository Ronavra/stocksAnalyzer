from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, mean_absolute_error

BASE_PRICE_FEATURES=[
    "return_1d","momentum_5d","momentum_20d","volatility_20d","volume_change_5d",
    "range_pct","close_vs_sma20","volume_ratio_20d","market_momentum_5d",
    "market_momentum_20d","market_volatility_20d","relative_momentum_5d",
    "relative_momentum_20d","drawdown_20d","drawdown_60d",
    "distance_to_support_60d","rebound_potential_20d","rebound_potential_60d",
]
CONTEXT_FEATURES=[
    "momentum_60d","momentum_120d","momentum_250d",
    "sector_momentum_5d","sector_momentum_20d",
    "relative_sector_momentum_5d","relative_sector_momentum_20d",
    "breadth_positive_20d","breadth_above_sma20","sector_breadth_positive_20d",
    "market_regime_score",
]
EARNINGS_FEATURES=[
    "earnings_eps_surprise","earnings_revenue_surprise","earnings_both_beat",
    "earnings_days_since","earnings_beat_streak","earnings_reaction_1d",
    "earnings_reaction_vs_spy",
]
FUND_FEATURES=[
    "fund_revenue_growth_yoy","fund_eps_growth_yoy","fund_operating_margin",
    "fund_net_margin","fund_fcf_margin","fund_debt_to_fcf","fund_cash_to_debt",
    "fund_age_days","fund_revenue_growth_accel","fund_eps_growth_accel",
    "fund_operating_margin_delta","fund_fcf_margin_delta","fund_fcf_to_net_income",
]
GUIDANCE_FEATURES=[
    "guidance_eps_gap","guidance_revenue_gap","guidance_eps_change",
    "guidance_revenue_change","guidance_days_since",
]
FEATURE_GROUPS={
    "price":BASE_PRICE_FEATURES,
    "context":CONTEXT_FEATURES,
    "earnings":EARNINGS_FEATURES,
    "fundamentals":FUND_FEATURES,
    "guidance":GUIDANCE_FEATURES,
}
DEFAULT_GROUPS=("price","context","earnings","fundamentals","guidance")
FEATURES=[x for g in DEFAULT_GROUPS for x in FEATURE_GROUPS[g]]
HORIZONS=(5,10,20)
MODEL_VERSION="calibrated-multifactor-v2"
_PREP_CACHE={}

@dataclass
class HorizonModel:
    horizon:int
    classifier:Any
    calibrator:Any
    regressor:Any
    diagnostics:dict
    feature_names:list[str]

    def _array(self,feature_dict):
        return np.asarray([[np.nan if feature_dict.get(k) is None else float(feature_dict[k]) for k in self.feature_names]],dtype=float)

    def probability(self,feature_dict):
        x=self._array(feature_dict)
        raw=float(self.classifier.predict_proba(x)[0,1])
        return float(self.calibrator.predict_proba(np.asarray([[raw]],dtype=float))[0,1])

    def expected_return(self,feature_dict):
        return float(self.regressor.predict(self._array(feature_dict))[0])


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError,ValueError):
        return None


def _clip(v,lo,hi):
    return None if v is None else max(lo,min(hi,float(v)))


def _paged(query_factory,page_size=1000):
    rows=[]; start=0
    while True:
        chunk=query_factory(start,start+page_size-1).execute().data or []
        rows.extend(chunk)
        if len(chunk)<page_size:
            break
        start+=page_size
    return rows


def _pct_decimal(v):
    v=_num(v)
    return None if v is None else _clip(v/100.0,-2.0,2.0)


def _ratio_change(cur,prev):
    cur=_num(cur); prev=_num(prev)
    return cur/prev-1 if cur is not None and prev not in (None,0) else None


def load_ttm_fundamentals(db):
    rows=_paged(lambda a,b: db.table("financial_metrics")
        .select("company_id,period_end,filed_date,revenue,operating_income,net_income,eps_diluted,free_cash_flow,cash,total_debt")
        .eq("period_type","ttm").order("company_id").order("filed_date").range(a,b))
    by_company={}
    for r in rows:
        if r.get("filed_date"):
            by_company.setdefault(r["company_id"],[]).append(r)

    snapshots={}
    for cid,items in by_company.items():
        items=sorted(items,key=lambda x:(x["filed_date"],x["period_end"]))
        built=[]
        for i,r in enumerate(items):
            cur_end=date.fromisoformat(r["period_end"])
            prior_yoy=None
            prior_snapshot=items[i-1] if i else None
            for q in reversed(items[:i]):
                gap=(cur_end-date.fromisoformat(q["period_end"])).days
                if 300<=gap<=450:
                    prior_yoy=q
                    break

            revenue=_num(r.get("revenue")); eps=_num(r.get("eps_diluted"))
            op=_num(r.get("operating_income")); net=_num(r.get("net_income")); fcf=_num(r.get("free_cash_flow"))
            debt=_num(r.get("total_debt")); cash=_num(r.get("cash"))
            prev_rev=_num(prior_yoy.get("revenue")) if prior_yoy else None
            prev_eps=_num(prior_yoy.get("eps_diluted")) if prior_yoy else None
            revenue_growth=_ratio_change(revenue,prev_rev)
            eps_growth=(eps/abs(prev_eps)-1) if eps is not None and prev_eps not in (None,0) else None
            op_margin=op/revenue if op is not None and revenue not in (None,0) else None
            net_margin=net/revenue if net is not None and revenue not in (None,0) else None
            fcf_margin=fcf/revenue if fcf is not None and revenue not in (None,0) else None

            prev_growth=prev_eps_growth=prev_op_margin=prev_fcf_margin=None
            if prior_snapshot:
                ps_end=date.fromisoformat(prior_snapshot["period_end"])
                ps_yoy=None
                for q in reversed(items[:i-1]):
                    gap=(ps_end-date.fromisoformat(q["period_end"])).days
                    if 300<=gap<=450:
                        ps_yoy=q
                        break
                ps_rev=_num(prior_snapshot.get("revenue")); ps_eps=_num(prior_snapshot.get("eps_diluted"))
                ps_op=_num(prior_snapshot.get("operating_income")); ps_fcf=_num(prior_snapshot.get("free_cash_flow"))
                py_rev=_num(ps_yoy.get("revenue")) if ps_yoy else None
                py_eps=_num(ps_yoy.get("eps_diluted")) if ps_yoy else None
                prev_growth=_ratio_change(ps_rev,py_rev)
                prev_eps_growth=(ps_eps/abs(py_eps)-1) if ps_eps is not None and py_eps not in (None,0) else None
                prev_op_margin=ps_op/ps_rev if ps_op is not None and ps_rev not in (None,0) else None
                prev_fcf_margin=ps_fcf/ps_rev if ps_fcf is not None and ps_rev not in (None,0) else None

            vals={
                "fund_revenue_growth_yoy":revenue_growth,
                "fund_eps_growth_yoy":eps_growth,
                "fund_operating_margin":op_margin,
                "fund_net_margin":net_margin,
                "fund_fcf_margin":fcf_margin,
                "fund_debt_to_fcf":debt/abs(fcf) if debt is not None and fcf not in (None,0) else None,
                "fund_cash_to_debt":cash/debt if cash is not None and debt not in (None,0) else None,
                "fund_revenue_growth_accel":revenue_growth-prev_growth if revenue_growth is not None and prev_growth is not None else None,
                "fund_eps_growth_accel":eps_growth-prev_eps_growth if eps_growth is not None and prev_eps_growth is not None else None,
                "fund_operating_margin_delta":op_margin-prev_op_margin if op_margin is not None and prev_op_margin is not None else None,
                "fund_fcf_margin_delta":fcf_margin-prev_fcf_margin if fcf_margin is not None and prev_fcf_margin is not None else None,
                "fund_fcf_to_net_income":fcf/net if fcf is not None and net not in (None,0) else None,
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


def load_price_rows(db,years=5):
    latest=(db.table("price_features").select("feature_date").order("feature_date",desc=True).limit(1).execute().data or [])
    if not latest:
        return [],None
    latest_date=date.fromisoformat(latest[0]["feature_date"])
    cutoff=(latest_date-timedelta(days=365*years+280)).isoformat()
    cols="company_id,feature_date,close,"+",".join(BASE_PRICE_FEATURES)+",forward_return_5d,forward_return_10d,forward_return_20d"
    rows=_paged(lambda a,b: db.table("price_features").select(cols)
        .gte("feature_date",cutoff).order("feature_date").order("company_id").range(a,b))
    return rows,latest_date.isoformat()


def _companies(db):
    rows=(db.table("companies").select("id,ticker,sector,scoring_profile").execute().data or [])
    return {r["id"]:r for r in rows}


def _derived_price_context(rows,companies):
    by_company={}
    by_date={}
    for r in rows:
        by_company.setdefault(r["company_id"],[]).append(r)
        by_date.setdefault(r["feature_date"],[]).append(r)

    longmom={}
    price_lookup={}
    for cid,items in by_company.items():
        items=sorted(items,key=lambda x:x["feature_date"])
        for i,r in enumerate(items):
            close=_num(r.get("close"))
            price_lookup[(cid,r["feature_date"])]=close
            rec={}
            for h in (60,120,250):
                prev=_num(items[i-h].get("close")) if i>=h else None
                rec[f"momentum_{h}d"]=close/prev-1 if close is not None and prev not in (None,0) else None
            longmom[(cid,r["feature_date"])]=rec

    context={}
    for d,items in by_date.items():
        m20=[_num(x.get("momentum_20d")) for x in items]
        sma=[_num(x.get("close_vs_sma20")) for x in items]
        valid20=[x for x in m20 if x is not None]
        validsma=[x for x in sma if x is not None]
        breadth20=sum(x>0 for x in valid20)/len(valid20) if valid20 else None
        breadthsma=sum(x>0 for x in validsma)/len(validsma) if validsma else None
        sectors={}
        for r in items:
            sector=(companies.get(r["company_id"]) or {}).get("sector") or "Unknown"
            sectors.setdefault(sector,[]).append(r)
        sector_stats={}
        for sector,srows in sectors.items():
            m5=[_num(x.get("momentum_5d")) for x in srows if _num(x.get("momentum_5d")) is not None]
            m20s=[_num(x.get("momentum_20d")) for x in srows if _num(x.get("momentum_20d")) is not None]
            sector_stats[sector]={
                "m5":sum(m5)/len(m5) if m5 else None,
                "m20":sum(m20s)/len(m20s) if m20s else None,
                "breadth20":sum(x>0 for x in m20s)/len(m20s) if m20s else None,
            }
        for r in items:
            cid=r["company_id"]; sector=(companies.get(cid) or {}).get("sector") or "Unknown"
            s=sector_stats.get(sector,{})
            m5=_num(r.get("momentum_5d")); m20r=_num(r.get("momentum_20d"))
            mm5=_num(r.get("market_momentum_5d")); mm20=_num(r.get("market_momentum_20d"))
            regime_parts=[
                1.0 if mm5 is not None and mm5>0 else 0.0 if mm5 is not None else None,
                1.0 if mm20 is not None and mm20>0 else 0.0 if mm20 is not None else None,
                1.0 if breadth20 is not None and breadth20>.5 else 0.0 if breadth20 is not None else None,
                1.0 if breadthsma is not None and breadthsma>.5 else 0.0 if breadthsma is not None else None,
            ]
            regime_parts=[x for x in regime_parts if x is not None]
            context[(cid,d)]={
                **longmom.get((cid,d),{}),
                "sector_momentum_5d":s.get("m5"),
                "sector_momentum_20d":s.get("m20"),
                "relative_sector_momentum_5d":m5-s["m5"] if m5 is not None and s.get("m5") is not None else None,
                "relative_sector_momentum_20d":m20r-s["m20"] if m20r is not None and s.get("m20") is not None else None,
                "breadth_positive_20d":breadth20,
                "breadth_above_sma20":breadthsma,
                "sector_breadth_positive_20d":s.get("breadth20"),
                "market_regime_score":sum(regime_parts)/len(regime_parts) if regime_parts else None,
            }
    return context,by_company,price_lookup


def _event_time_before_open(v):
    if not v:
        return False
    return str(v)[:5] < "09:30"


def _event_time_after_close(v):
    if not v:
        return False
    return str(v)[:5] >= "16:00"


def _trading_dates(items):
    return [r["feature_date"] for r in items]


def _price_at_or_before(items,d):
    dates=_trading_dates(items); i=bisect_right(dates,d)-1
    return (items[i]["feature_date"],_num(items[i].get("close"))) if i>=0 else (None,None)


def _price_after(items,d):
    dates=_trading_dates(items); i=bisect_right(dates,d)
    return (items[i]["feature_date"],_num(items[i].get("close"))) if i<len(items) else (None,None)


def _price_exact(items,d):
    dates=_trading_dates(items); i=bisect_right(dates,d)-1
    if i>=0 and items[i]["feature_date"]==d:
        return _num(items[i].get("close"))
    return None


def load_earnings_features(db,by_company,spy_items):
    rows=_paged(lambda a,b: db.table("earnings_events")
        .select("company_id,reported_date,event_time,surprise_percent,revenue_surprise_percent,source")
        .eq("source","massive_benzinga").order("company_id").order("reported_date").range(a,b))
    out={}
    groups={}
    for r in rows:
        groups.setdefault(r["company_id"],[]).append(r)

    for cid,events in groups.items():
        prices=by_company.get(cid) or []
        if not prices:
            continue
        records=[]; streak=0
        for e in sorted(events,key=lambda x:x["reported_date"]):
            eps=_pct_decimal(e.get("surprise_percent"))
            rev=_pct_decimal(e.get("revenue_surprise_percent"))
            beat=eps is not None and eps>0
            streak=streak+1 if beat else 0
            event_date=e["reported_date"]
            before_open=_event_time_before_open(e.get("event_time"))
            after_close=_event_time_after_close(e.get("event_time"))
            if before_open:
                reaction_date=event_date if _price_exact(prices,event_date) is not None else _price_after(prices,event_date)[0]
                prior_date=(date.fromisoformat(event_date)-timedelta(days=1)).isoformat()
                _,base=_price_at_or_before(prices,prior_date)
            else:
                base=_price_exact(prices,event_date)
                if base is None:
                    _,base=_price_at_or_before(prices,event_date)
                reaction_date,_=_price_after(prices,event_date)
            reaction=_price_exact(prices,reaction_date) if reaction_date else None
            reaction_ret=reaction/base-1 if reaction is not None and base not in (None,0) else None

            spy_base=None; spy_reaction=None
            if reaction_date and spy_items:
                if before_open:
                    prior_date=(date.fromisoformat(event_date)-timedelta(days=1)).isoformat()
                    _,spy_base=_price_at_or_before(spy_items,prior_date)
                else:
                    spy_base=_price_exact(spy_items,event_date)
                    if spy_base is None:
                        _,spy_base=_price_at_or_before(spy_items,event_date)
                spy_reaction=_price_exact(spy_items,reaction_date)
            spy_ret=spy_reaction/spy_base-1 if spy_reaction is not None and spy_base not in (None,0) else None
            available_date=reaction_date if after_close else event_date
            records.append({
                "available_date":available_date or event_date,
                "reported_date":event_date,
                "reaction_date":reaction_date,
                "values":{
                    "earnings_eps_surprise":eps,
                    "earnings_revenue_surprise":rev,
                    "earnings_both_beat":1.0 if eps is not None and rev is not None and eps>0 and rev>0 else 0.0 if eps is not None and rev is not None else None,
                    "earnings_beat_streak":float(streak),
                    "earnings_reaction_1d":reaction_ret,
                    "earnings_reaction_vs_spy":reaction_ret-spy_ret if reaction_ret is not None and spy_ret is not None else None,
                },
            })
        out[cid]=records
    return out


def earnings_asof(events,cid,asof):
    items=events.get(cid) or []
    if not items:
        return {k:None for k in EARNINGS_FEATURES}
    keys=[x["available_date"] for x in items]
    i=bisect_right(keys,asof)-1
    if i<0:
        return {k:None for k in EARNINGS_FEATURES}
    item=items[i]
    vals=dict(item["values"])
    vals["earnings_days_since"]=(date.fromisoformat(asof)-date.fromisoformat(item["reported_date"])).days
    # A close reaction is only known after its reaction trading session.
    if item.get("reaction_date") and asof<item["reaction_date"]:
        vals["earnings_reaction_1d"]=None
        vals["earnings_reaction_vs_spy"]=None
    return vals


def load_guidance_features(db):
    rows=_paged(lambda a,b: db.table("corporate_guidance_events")
        .select("company_id,event_date,eps_guidance_low,eps_guidance_high,revenue_guidance_low,revenue_guidance_high,consensus_eps_at_event,consensus_revenue_at_event,previous_eps_guidance_low,previous_eps_guidance_high,previous_revenue_guidance_low,previous_revenue_guidance_high")
        .order("company_id").order("event_date").range(a,b))
    out={}
    for r in rows:
        eps_mid=None
        if _num(r.get("eps_guidance_low")) is not None and _num(r.get("eps_guidance_high")) is not None:
            eps_mid=(_num(r["eps_guidance_low"])+_num(r["eps_guidance_high"]))/2
        rev_mid=None
        if _num(r.get("revenue_guidance_low")) is not None and _num(r.get("revenue_guidance_high")) is not None:
            rev_mid=(_num(r["revenue_guidance_low"])+_num(r["revenue_guidance_high"]))/2
        peps=None
        if _num(r.get("previous_eps_guidance_low")) is not None and _num(r.get("previous_eps_guidance_high")) is not None:
            peps=(_num(r["previous_eps_guidance_low"])+_num(r["previous_eps_guidance_high"]))/2
        prevrev=None
        if _num(r.get("previous_revenue_guidance_low")) is not None and _num(r.get("previous_revenue_guidance_high")) is not None:
            prevrev=(_num(r["previous_revenue_guidance_low"])+_num(r["previous_revenue_guidance_high"]))/2
        cons_eps=_num(r.get("consensus_eps_at_event")); cons_rev=_num(r.get("consensus_revenue_at_event"))
        vals={
            "guidance_eps_gap":eps_mid/abs(cons_eps)-1 if eps_mid is not None and cons_eps not in (None,0) else None,
            "guidance_revenue_gap":rev_mid/cons_rev-1 if rev_mid is not None and cons_rev not in (None,0) else None,
            "guidance_eps_change":eps_mid/abs(peps)-1 if eps_mid is not None and peps not in (None,0) else None,
            "guidance_revenue_change":rev_mid/prevrev-1 if rev_mid is not None and prevrev not in (None,0) else None,
        }
        out.setdefault(r["company_id"],[]).append({"event_date":r["event_date"],"values":vals})
    return out


def guidance_asof(events,cid,asof):
    items=events.get(cid) or []
    if not items:
        return {k:None for k in GUIDANCE_FEATURES}
    keys=[x["event_date"] for x in items]
    i=bisect_right(keys,asof)-1
    if i<0:
        return {k:None for k in GUIDANCE_FEATURES}
    item=items[i]; vals=dict(item["values"])
    vals["guidance_days_since"]=(date.fromisoformat(asof)-date.fromisoformat(item["event_date"])).days
    return vals


def _prepare(db,years=5):
    rows,latest_date=load_price_rows(db,years)
    cache_key=(latest_date,years,len(rows))
    if cache_key in _PREP_CACHE:
        return _PREP_CACHE[cache_key]
    companies=_companies(db)
    context,by_company,_=_derived_price_context(rows,companies)
    spy_id=next((cid for cid,c in companies.items() if c.get("ticker")=="SPY"),None)
    spy_items=by_company.get(spy_id,[]) if spy_id else []
    fund=load_ttm_fundamentals(db)
    earnings=load_earnings_features(db,by_company,spy_items)
    guidance=load_guidance_features(db)

    feature_dicts={}
    for r in rows:
        cid=r["company_id"]; d=r["feature_date"]
        fd={k:_num(r.get(k)) for k in BASE_PRICE_FEATURES}
        fd.update(context.get((cid,d),{}))
        fd.update(earnings_asof(earnings,cid,d))
        fd.update(fundamental_asof(fund,cid,d))
        fd.update(guidance_asof(guidance,cid,d))
        feature_dicts[(cid,d)]=fd

    prepared={
        "rows":rows,"latest_date":latest_date,"companies":companies,
        "features":feature_dicts,"fundamental_companies":len(fund),
        "earnings_companies":len(earnings),"guidance_companies":len(guidance),
    }
    _PREP_CACHE.clear(); _PREP_CACHE[cache_key]=prepared
    return prepared


def _classifier():
    return HistGradientBoostingClassifier(
        max_depth=3,max_iter=100,learning_rate=.05,l2_regularization=2.0,
        min_samples_leaf=40,random_state=42
    )


def _regressor():
    return HistGradientBoostingRegressor(
        max_depth=3,max_iter=100,learning_rate=.05,l2_regularization=2.0,
        min_samples_leaf=40,random_state=42
    )


def _selected_features(groups):
    groups=tuple(groups or DEFAULT_GROUPS)
    return [x for g in groups for x in FEATURE_GROUPS[g]]


def fit_models(db,years=5,min_rows=5000,groups=None):
    prep=_prepare(db,years)
    price_rows=prep["rows"]; latest_date=prep["latest_date"]
    if not price_rows:
        return {},{"error":"no price features"}
    feature_names=_selected_features(groups)
    all_dates=sorted({r["feature_date"] for r in price_rows})
    date_index={d:i for i,d in enumerate(all_dates)}
    sampled_dates={d for i,d in enumerate(all_dates) if i%5==0}
    enriched=[
        (r,prep["features"][(r["company_id"],r["feature_date"])])
        for r in price_rows if r["feature_date"] in sampled_dates
    ]

    models={}
    for h in HORIZONS:
        label=f"forward_return_{h}d"
        data=[(r,fd,_num(r.get(label))) for r,fd in enriched if r.get(label) is not None]
        if len(data)<min_rows:
            continue
        data.sort(key=lambda z:z[0]["feature_date"])
        dates=sorted({r["feature_date"] for r,_,_ in data})
        if len(dates)<120:
            continue

        fold_starts=[int(len(dates)*p) for p in (.58,.70,.82)]
        raw_oof=[]; y_oof=[]
        for fi,start in enumerate(fold_starts):
            end=fold_starts[fi+1] if fi+1<len(fold_starts) else len(dates)
            if start>=end:
                continue
            val_dates=set(dates[start:end])
            val_start=dates[start]
            purge_i=max(0,date_index[val_start]-h)
            cutoff=all_dates[purge_i]
            train=[z for z in data if z[0]["feature_date"]<cutoff]
            valid=[z for z in data if z[0]["feature_date"] in val_dates]
            if len(train)<min_rows//2 or len(valid)<500:
                continue
            Xtr=np.asarray([[np.nan if fd.get(k) is None else float(fd[k]) for k in feature_names] for _,fd,_ in train],dtype=float)
            ytr=np.asarray([target>0 for _,_,target in train],dtype=int)
            Xv=np.asarray([[np.nan if fd.get(k) is None else float(fd[k]) for k in feature_names] for _,fd,_ in valid],dtype=float)
            yv=np.asarray([target>0 for _,_,target in valid],dtype=int)
            clf=_classifier(); clf.fit(Xtr,ytr)
            raw=clf.predict_proba(Xv)[:,1]
            raw_oof.extend(raw.tolist()); y_oof.extend(yv.tolist())

        if len(raw_oof)<1000 or len(set(y_oof))<2:
            continue
        raw_arr=np.asarray(raw_oof,dtype=float); y_arr=np.asarray(y_oof,dtype=int)
        calibrator=LogisticRegression(C=1.0,solver="lbfgs")
        calibrator.fit(raw_arr.reshape(-1,1),y_arr)
        cal=calibrator.predict_proba(raw_arr.reshape(-1,1))[:,1]
        base=np.full_like(cal,float(y_arr.mean()),dtype=float)

        X=np.asarray([[np.nan if fd.get(k) is None else float(fd[k]) for k in feature_names] for _,fd,_ in data],dtype=float)
        y_cls=np.asarray([target>0 for _,_,target in data],dtype=int)
        y_ret=np.asarray([target for _,_,target in data],dtype=float)
        clf=_classifier(); clf.fit(X,y_cls)
        reg=_regressor(); reg.fit(X,y_ret)
        tail=min(10000,len(X)); pred_ret=reg.predict(X[-tail:]); actual_ret=y_ret[-tail:]
        cb=float(brier_score_loss(y_arr,cal)); bb=float(brier_score_loss(y_arr,base))
        diagnostics={
            "model_version":MODEL_VERSION,"horizon_days":h,
            "training_rows":len(data),"training_dates":len(dates),"oof_rows":len(y_oof),
            "oof_up_rate":float(y_arr.mean()),"raw_brier":float(brier_score_loss(y_arr,raw_arr)),
            "calibrated_brier":cb,"baseline_brier":bb,"brier_skill":(bb-cb)/bb if bb else None,
            "calibration_beats_baseline":bool(cb<bb),
            "recent_train_mae":float(mean_absolute_error(actual_ret,pred_ret)),
            "feature_count":len(feature_names),"feature_groups":list(groups or DEFAULT_GROUPS),
        }
        models[h]=HorizonModel(h,clf,calibrator,reg,diagnostics,feature_names)

    meta={
        "latest_feature_date":latest_date,"features":feature_names,
        "feature_groups":list(groups or DEFAULT_GROUPS),
        "fundamental_companies":prep["fundamental_companies"],
        "earnings_companies":prep["earnings_companies"],
        "guidance_companies":prep["guidance_companies"],
    }
    return models,meta


def predict_current(db,models,years=5):
    prep=_prepare(db,years)
    d=prep["latest_date"]
    rows=[r for r in prep["rows"] if r["feature_date"]==d]
    out={}
    for r in rows:
        cid=r["company_id"]; fd=prep["features"].get((cid,d),{})
        out[cid]={}
        for h,m in models.items():
            present=sum(fd.get(k) is not None for k in m.feature_names)/len(m.feature_names)
            out[cid][h]={
                "probability_up":m.probability(fd),
                "expected_return":m.expected_return(fd),
                "feature_coverage":present,
                "diagnostics":m.diagnostics,
            }
    return out,d
