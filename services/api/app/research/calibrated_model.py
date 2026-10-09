from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from .financial_quality import MAX_TTM_AGE_DAYS
from .model_identity import HORIZONS, MODEL_VERSION
from .observations import available, close_cutoff, member_asof

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
    "fund_return_on_equity","fund_cet1_ratio",
    "fund_age_days","fund_revenue_growth_accel","fund_eps_growth_accel",
    "fund_operating_margin_delta","fund_fcf_margin_delta","fund_fcf_to_net_income",
]
VALUATION_FEATURES=[
    "valuation_pe","valuation_fcf_yield",
    "valuation_pe_vs_sector","valuation_fcf_yield_vs_sector",
]
GUIDANCE_FEATURES=[
    "guidance_eps_gap","guidance_revenue_gap","guidance_eps_change",
    "guidance_revenue_change","guidance_days_since",
]
NEWS_FEATURES=["news_articles_7d","news_provider_sentiment_7d","news_sentiment_observations_7d"]
FEATURE_GROUPS={
    "price":BASE_PRICE_FEATURES,
    "context":CONTEXT_FEATURES,
    "earnings":EARNINGS_FEATURES,
    "fundamentals":FUND_FEATURES,
    "valuation":VALUATION_FEATURES,
    "guidance":GUIDANCE_FEATURES,
    "news":NEWS_FEATURES,
}
DEFAULT_GROUPS=("price","context","earnings","fundamentals","valuation","guidance","news")
FEATURES=[x for g in DEFAULT_GROUPS for x in FEATURE_GROUPS[g]]
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
        if not self.diagnostics.get("return_mae_beats_baseline"):
            return None
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
    # Today's restated financial rows are never projected into old training dates.
    versions=_paged(lambda a,b: db.table("financial_metric_versions")
        .select("company_id,period_end,observed_at,provenance,snapshot")
        .eq("period_type","ttm").order("company_id").order("observed_at").range(a,b))
    out={}
    for version in versions:
        row=version.get("snapshot") or {}
        if row.get("filed_date"):
            out.setdefault(version["company_id"],[]).append({**row,"observed_at":version["observed_at"],"_raw_financial":True})
    return out


def observed_fundamental_asof(items,asof):
    from .observations import available, close_cutoff, member_asof
    from .financial_ranking import financial_snapshot, factors
    cutoff=close_cutoff(asof)
    observed=[r for r in items if available(r,cutoff)]
    chosen={}
    for row in observed:
        previous=chosen.get(row["period_end"])
        if previous is None or row["observed_at"]>previous["observed_at"]:
            chosen[row["period_end"]]=row
    snapshot,error=financial_snapshot(list(chosen.values()),asof,live=False,point_in_time=True)
    if error:
        return {k:None for k in FUND_FEATURES}
    current=snapshot["latest"]; values=factors(snapshot,1.)
    old=snapshot.get("previous")
    older=[r for r in chosen.values() if old and 300<=(date.fromisoformat(old["period_end"])-date.fromisoformat(r["period_end"])).days<=450]
    prior=factors({"latest":old,"previous":max(older,key=lambda r:r["period_end"],default=None)},1.) if old else {}
    def change(key):
        a=values.get(key); b=prior.get(key)
        return a-b if a is not None and b is not None else None
    return {
        "_ttm_eps":_num(current.get("eps_diluted")),"_ttm_fcf":_num(current.get("free_cash_flow")),
        "_shares_outstanding":_num(current.get("shares_outstanding")),
        "fund_revenue_growth_yoy":values["revenue_growth"],"fund_eps_growth_yoy":values["eps_growth"],
        "fund_operating_margin":values["operating_margin"],"fund_net_margin":values["net_margin"],
        "fund_fcf_margin":values["fcf_margin"],"fund_debt_to_fcf":_safe_ratio(current.get("total_debt"),current.get("free_cash_flow")),
        "fund_cash_to_debt":_safe_ratio(current.get("cash"),current.get("total_debt")),
        "fund_age_days":(date.fromisoformat(asof)-date.fromisoformat(current["filed_date"])).days,
        "fund_revenue_growth_accel":change("revenue_growth"),"fund_eps_growth_accel":change("eps_growth"),
        "fund_operating_margin_delta":change("operating_margin"),"fund_fcf_margin_delta":change("fcf_margin"),
        "fund_fcf_to_net_income":values["cash_conversion"],"fund_return_on_equity":values["return_on_equity"],
        "fund_cet1_ratio":values["cet1_ratio"],
    }


def _safe_ratio(numerator,denominator):
    a=_num(numerator); b=_num(denominator)
    return a/b if a is not None and b is not None and b>0 else None


def fundamental_asof(snapshots,cid,asof):
    items=snapshots.get(cid) or []
    if not items:
        return {k:None for k in FUND_FEATURES}
    if items[0].get("_raw_financial"):
        return observed_fundamental_asof(items,asof)
    keys=[x["filed_date"] for x in items]
    i=bisect_right(keys,asof)-1
    if i<0:
        return {k:None for k in FUND_FEATURES}
    # A newly filed comparative or amendment for an older year must not
    # replace the newest financial period available at this historical close.
    item=max(items[:i+1],key=lambda x:(x["period_end"],x["filed_date"]))
    age=(date.fromisoformat(asof)-date.fromisoformat(item["period_end"])).days
    if not 0<=age<=MAX_TTM_AGE_DAYS:
        return {k:None for k in FUND_FEATURES}
    out=dict(item["values"])
    out["fund_age_days"]=(date.fromisoformat(asof)-date.fromisoformat(item["filed_date"])).days
    return out


def load_price_rows(db,years=5):
    from app.db.market_history import require_full_history
    require_full_history(db)
    latest=(db.table("price_features").select("feature_date").order("feature_date",desc=True).limit(1).execute().data or [])
    if not latest:
        return [],None
    latest_date=date.fromisoformat(latest[0]["feature_date"])
    cutoff=(latest_date-timedelta(days=365*years+280)).isoformat()
    cols="company_id,feature_date,close,"+",".join(BASE_PRICE_FEATURES)+",forward_return_5d,forward_return_10d,forward_return_20d"
    company_ids=[r["id"] for r in (db.table("companies").select("id").execute().data or [])]
    rows=[]
    # Fetch per company so PostgreSQL can use the (company_id, feature_date)
    # index. A single multi-year ordered scan was hitting Supabase's statement timeout.
    for n,cid in enumerate(company_ids,1):
        start=0
        while True:
            chunk=(db.table("price_features").select(cols)
                   .eq("company_id",cid).gte("feature_date",cutoff)
                   .order("feature_date").range(start,start+999).execute().data or [])
            rows.extend(chunk)
            if len(chunk)<1000:
                break
            start+=1000
        if n%50==0:
            print(f"Loaded model price features for {n}/{len(company_ids)} companies",flush=True)
    return rows,latest_date.isoformat()


def _companies(db):
    rows=(db.table("companies").select("id,ticker,sector,scoring_profile").execute().data or [])
    return {r["id"]:r for r in rows}


def _derived_price_context(rows,companies,include_dates,eligible=None):
    by_company={}
    by_date={}
    for r in rows:
        by_company.setdefault(r["company_id"],[]).append(r)
        if r["feature_date"] in include_dates and (eligible is None or eligible(r["company_id"],r["feature_date"])):
            by_date.setdefault(r["feature_date"],[]).append(r)

    longmom={}
    for cid,items in by_company.items():
        items=sorted(items,key=lambda x:x["feature_date"])
        for i,r in enumerate(items):
            if r["feature_date"] not in include_dates:
                continue
            close=_num(r.get("close"))
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
    return context,by_company


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
    rows=_paged(lambda a,b: db.table("earnings_event_versions")
        .select("event_id,company_id,observed_at,snapshot")
        .order("company_id").order("observed_at").range(a,b))
    out={}
    groups={}
    for version in rows:
        r={**version["snapshot"],"observed_at":version["observed_at"],"event_id":version["event_id"]}
        if r.get("source")=="massive_benzinga":
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
                "observed_at":e["observed_at"],"event_id":e["event_id"],"reported":e.get("reported_eps") is not None,
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
    latest={}
    for candidate in items:
        if candidate["available_date"]>asof or not available(candidate,close_cutoff(asof)):
            continue
        key=candidate["event_id"]
        if key not in latest or candidate["observed_at"]>latest[key]["observed_at"]:
            latest[key]=candidate
    known=[x for x in latest.values() if x.get("reported")]
    if not known:
        return {k:None for k in EARNINGS_FEATURES}
    ordered=sorted(known,key=lambda x:(x["reported_date"],x["observed_at"]))
    item=ordered[-1]
    vals=dict(item["values"])
    streak=0
    for event in reversed(ordered):
        eps=event["values"].get("earnings_eps_surprise")
        if eps is None or eps<=0:
            break
        streak+=1
    vals["earnings_beat_streak"]=float(streak)
    vals["earnings_days_since"]=(date.fromisoformat(asof)-date.fromisoformat(item["reported_date"])).days
    # A close reaction is only known after its reaction trading session.
    if item.get("reaction_date") and asof<item["reaction_date"]:
        vals["earnings_reaction_1d"]=None
        vals["earnings_reaction_vs_spy"]=None
    return vals


def load_guidance_features(db):
    rows=_paged(lambda a,b: db.table("corporate_guidance_events")
        .select("company_id,event_date,eps_guidance_low,eps_guidance_high,revenue_guidance_low,revenue_guidance_high,consensus_eps_at_event,consensus_revenue_at_event,previous_eps_guidance_low,previous_eps_guidance_high,previous_revenue_guidance_low,previous_revenue_guidance_high,fiscal_year,fiscal_period,captured_at,published_at,eps_method,revenue_method,source")
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
            "guidance_eps_gap":(eps_mid-cons_eps)/abs(cons_eps) if eps_mid is not None and cons_eps not in (None,0) else None,
            "guidance_revenue_gap":rev_mid/cons_rev-1 if rev_mid is not None and cons_rev not in (None,0) else None,
            "guidance_eps_change":(eps_mid-peps)/abs(peps) if eps_mid is not None and peps not in (None,0) else None,
            "guidance_revenue_change":rev_mid/prevrev-1 if rev_mid is not None and prevrev not in (None,0) else None,
        }
        out.setdefault(r["company_id"],[]).append({"event_date":r["event_date"],"captured_at":r["captured_at"],"published_at":r.get("published_at"),"values":vals,"eps_method":r.get("eps_method"),"source":r.get("source"),"fiscal_year":r.get("fiscal_year"),"fiscal_period":r.get("fiscal_period")})
    return out


def guidance_asof(events,cid,asof):
    items=events.get(cid) or []
    if not items:
        return {k:None for k in GUIDANCE_FEATURES}
    eligible=[x for x in items if x["event_date"]<=asof and available(x,close_cutoff(asof),observed_key="captured_at")]
    if not eligible:
        return {k:None for k in GUIDANCE_FEATURES}
    item=max(eligible,key=lambda x:(x["event_date"],x["captured_at"]))
    vals={k:None for k in GUIDANCE_FEATURES}
    # SEC releases store each accounting basis / metric separately. Merge
    # same-release fields without combining different forecast fiscal periods.
    peers=[x for x in eligible if x["event_date"]==item["event_date"]
           and x.get("fiscal_year")==item.get("fiscal_year")
           and x.get("fiscal_period")==item.get("fiscal_period")]
    for peer in sorted(peers,key=lambda x:x["captured_at"]):
        for key,value in peer["values"].items():
            if key.startswith("guidance_eps") and str(peer.get("eps_method") or "").lower() not in ("gaap","adjusted","non-gaap"):
                continue
            if value is not None:
                vals[key]=value
    vals["guidance_days_since"]=(date.fromisoformat(asof)-date.fromisoformat(item["event_date"])).days
    return vals


def load_news_features(db):
    rows=_paged(lambda a,b:db.table("news_events").select("company_id,published_at,created_at,sentiment")
                .order("company_id").order("published_at").range(a,b))
    grouped={}
    for row in rows:
        grouped.setdefault(row["company_id"],[]).append(row)
    return grouped


def news_asof(events,cid,asof):
    from .news import news_summary
    values=news_summary(events.get(cid,[]),close_cutoff(asof))
    # Absence of observed articles is missing source coverage, not neutral
    # sentiment or proof that nothing happened to this company.
    return {"news_articles_7d":values["articles"] if values["articles"] else None,
            "news_provider_sentiment_7d":values["mean_provider_sentiment"],
            "news_sentiment_observations_7d":values["sentiment_observations"] if values["articles"] else None}


def _prepare(db,years=5):
    # One immutable input snapshot per client/process and lookback. Check BEFORE
    # downloading multi-year prices so feature variants and forecasts reuse it.
    cache_key=(db,years)
    if cache_key in _PREP_CACHE:
        return _PREP_CACHE[cache_key]
    rows,latest_date=load_price_rows(db,years)
    all_dates=sorted({r["feature_date"] for r in rows})
    sampled_dates={d for i,d in enumerate(all_dates) if i%5==0}
    if latest_date:
        sampled_dates.add(latest_date)
    companies=_companies(db)
    memberships=_paged(lambda a,b:db.table("index_memberships")
                       .select("company_id,effective_from,effective_to,captured_at")
                       .eq("index_code","SP500").order("id").range(a,b)) if db is not None else []
    eligible=(lambda cid,day:member_asof(memberships,cid,day)) if db is not None else None
    context,by_company=_derived_price_context(rows,companies,sampled_dates,eligible)
    spy_id=next((cid for cid,c in companies.items() if c.get("ticker")=="SPY"),None)
    spy_items=by_company.get(spy_id,[]) if spy_id else []
    fund=load_ttm_fundamentals(db)
    earnings=load_earnings_features(db,by_company,spy_items)
    guidance=load_guidance_features(db)
    news=load_news_features(db) if db is not None else {}

    selected_rows=[r for r in rows if r["feature_date"] in sampled_dates
                   and (eligible is None or eligible(r["company_id"],r["feature_date"]))]
    feature_dicts={}
    for r in selected_rows:
        cid=r["company_id"]; d=r["feature_date"]
        fd={k:_num(r.get(k)) for k in BASE_PRICE_FEATURES}
        fd.update(context.get((cid,d),{}))
        fd.update(earnings_asof(earnings,cid,d))
        fd.update(fundamental_asof(fund,cid,d))
        fd.update(guidance_asof(guidance,cid,d))
        fd.update(news_asof(news,cid,d))
        eps=_num(fd.get("_ttm_eps")); fcf=_num(fd.get("_ttm_fcf")); shares=_num(fd.get("_shares_outstanding")); close=_num(r.get("close"))
        pe=close/eps if close is not None and eps is not None and eps>0 else None
        market_cap=close*shares if close is not None and shares is not None and shares>0 else None
        fcf_yield=fcf/market_cap if fcf is not None and market_cap not in (None,0) else None
        fd["valuation_pe"]=_clip(pe,0,250) if pe is not None else None
        fd["valuation_fcf_yield"]=_clip(fcf_yield,-1,1) if fcf_yield is not None else None
        fd["valuation_pe_vs_sector"]=None
        fd["valuation_fcf_yield_vs_sector"]=None
        feature_dicts[(cid,d)]=fd

    # Cross-sectional sector-relative valuation, using only point-in-time
    # fundamentals available on each feature date.
    rows_by_date={}
    for r in selected_rows:
        rows_by_date.setdefault(r["feature_date"],[]).append(r)
    for d,day_rows in rows_by_date.items():
        sector_values={}
        for r in day_rows:
            cid=r["company_id"]; sector=(companies.get(cid) or {}).get("sector") or "Unknown"
            fd=feature_dicts[(cid,d)]
            sector_values.setdefault(sector,{"pe":[],"fy":[]})
            if fd.get("valuation_pe") is not None:
                sector_values[sector]["pe"].append(fd["valuation_pe"])
            if fd.get("valuation_fcf_yield") is not None:
                sector_values[sector]["fy"].append(fd["valuation_fcf_yield"])
        for r in day_rows:
            cid=r["company_id"]; sector=(companies.get(cid) or {}).get("sector") or "Unknown"
            fd=feature_dicts[(cid,d)]; vals=sector_values.get(sector,{})
            pe_med=float(np.median(vals.get("pe",[]))) if vals.get("pe") else None
            fy_med=float(np.median(vals.get("fy",[]))) if vals.get("fy") else None
            pe=fd.get("valuation_pe"); fy=fd.get("valuation_fcf_yield")
            fd["valuation_pe_vs_sector"]=pe/pe_med-1 if pe is not None and pe_med not in (None,0) else None
            fd["valuation_fcf_yield_vs_sector"]=fy-fy_med if fy is not None and fy_med is not None else None

    prepared={
        "rows":selected_rows,"all_dates":all_dates,"latest_date":latest_date,"companies":companies,
        "features":feature_dicts,"fundamental_companies":len(fund),
        "earnings_companies":len(earnings),"guidance_companies":len(guidance),"news_companies":len(news),
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
    all_dates=prep["all_dates"]
    date_index={d:i for i,d in enumerate(all_dates)}
    enriched=[
        (r,prep["features"][(r["company_id"],r["feature_date"])])
        for r in price_rows
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
        fold_outputs=[]
        return_holdout_mae=return_baseline_mae=None
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
            fold_outputs.append((raw,np.asarray(yv,dtype=int),[z[0]["feature_date"] for z in valid]))
            if fi==2:
                train_returns=np.asarray([target for _,_,target in train],dtype=float)
                valid_returns=np.asarray([target for _,_,target in valid],dtype=float)
                validation_regressor=_regressor(); validation_regressor.fit(Xtr,train_returns)
                return_holdout_mae=float(mean_absolute_error(valid_returns,validation_regressor.predict(Xv)))
                return_baseline_mae=float(mean_absolute_error(
                    valid_returns,np.full(len(valid_returns),float(train_returns.mean()))
                ))

        # Calibration, feature-group selection and the final audit must use
        # different chronological periods. Purge observations whose forward
        # labels cross either boundary before using them to make a decision.
        if len(fold_outputs)!=3:
            continue
        def before_boundary(output,boundary):
            raw,labels,observation_dates=output
            cutoff=all_dates[max(0,date_index[boundary]-h)]
            mask=np.asarray([d<cutoff for d in observation_dates],dtype=bool)
            return raw[mask],labels[mask]

        calibration_raw,calibration_y=before_boundary(fold_outputs[0],dates[fold_starts[1]])
        selection_raw,selection_y=before_boundary(fold_outputs[1],dates[fold_starts[2]])
        holdout_raw,holdout_y,_=fold_outputs[2]
        if min(len(calibration_y),len(selection_y),len(holdout_y))<1000 or len(set(calibration_y))<2:
            continue
        calibrator=LogisticRegression(C=1.0,solver="lbfgs")
        calibrator.fit(calibration_raw.reshape(-1,1),calibration_y)
        selection_cal=calibrator.predict_proba(selection_raw.reshape(-1,1))[:,1]
        selection_base=np.full_like(selection_cal,float(calibration_y.mean()),dtype=float)
        selection_cb=float(brier_score_loss(selection_y,selection_cal))
        selection_bb=float(brier_score_loss(selection_y,selection_base))

        # Only the pre-holdout predictions train the deployed calibrator.
        # The final period remains untouched until its Brier score is computed.
        prior_raw=np.concatenate((calibration_raw,selection_raw))
        prior_y=np.concatenate((calibration_y,selection_y))
        calibrator.fit(prior_raw.reshape(-1,1),prior_y)
        holdout_cal=calibrator.predict_proba(holdout_raw.reshape(-1,1))[:,1]
        holdout_base=np.full_like(holdout_cal,float(prior_y.mean()),dtype=float)

        X=np.asarray([[np.nan if fd.get(k) is None else float(fd[k]) for k in feature_names] for _,fd,_ in data],dtype=float)
        y_cls=np.asarray([target>0 for _,_,target in data],dtype=int)
        y_ret=np.asarray([target for _,_,target in data],dtype=float)
        clf=_classifier(); clf.fit(X,y_cls)
        reg=_regressor(); reg.fit(X,y_ret)
        tail=min(10000,len(X)); pred_ret=reg.predict(X[-tail:]); actual_ret=y_ret[-tail:]
        cb=float(brier_score_loss(holdout_y,holdout_cal))
        bb=float(brier_score_loss(holdout_y,holdout_base))
        diagnostics={
            "model_version":MODEL_VERSION,"horizon_days":h,
            "evaluation_protocol":"chronological_calibration_selection_holdout_v4",
            "training_rows":len(data),"training_dates":len(dates),"oof_rows":len(holdout_y),
            "calibration_rows":len(calibration_y),"selection_rows":len(selection_y),
            "oof_up_rate":float(holdout_y.mean()),"raw_brier":float(brier_score_loss(holdout_y,holdout_raw)),
            "selection_calibrated_brier":selection_cb,"selection_baseline_brier":selection_bb,
            "selection_beats_baseline":bool(selection_cb<selection_bb),
            "calibrated_brier":cb,"baseline_brier":bb,"brier_skill":(bb-cb)/bb if bb else None,
            "calibration_beats_baseline":bool(cb<bb),
            "return_holdout_mae":return_holdout_mae,"return_baseline_mae":return_baseline_mae,
            "return_mae_beats_baseline":bool(return_holdout_mae is not None and return_holdout_mae<return_baseline_mae),
            "recent_train_mae":float(mean_absolute_error(actual_ret,pred_ret)),
            "feature_count":len(feature_names),"feature_groups":list(groups or DEFAULT_GROUPS),
        }
        models[h]=HorizonModel(h,clf,calibrator,reg,diagnostics,feature_names)

    available_dates=sorted({r["feature_date"] for r in price_rows})
    evaluation_start=available_dates[int(len(available_dates)*.70)] if available_dates else latest_date
    meta={
        "membership_history_mode":"recorded_observed_intervals",
        "observed_training_family_dates":{g:len({day for (cid,day),values in prep["features"].items()
                                              if day<evaluation_start and any(values.get(k) is not None for k in FEATURE_GROUPS[g])})
                                          for g in ("fundamentals","valuation","earnings","guidance","news")},
        "latest_feature_date":latest_date,"features":feature_names,
        "feature_groups":list(groups or DEFAULT_GROUPS),
        "fundamental_companies":prep["fundamental_companies"],
        "earnings_companies":prep["earnings_companies"],
        "guidance_companies":prep["guidance_companies"],
        "news_companies":prep.get("news_companies",0),
        "observed_family_dates":{g:len({day for (cid,day),values in prep["features"].items()
                                     if any(values.get(k) is not None for k in FEATURE_GROUPS[g])})
                                  for g in ("fundamentals","valuation","earnings","guidance","news")},
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
