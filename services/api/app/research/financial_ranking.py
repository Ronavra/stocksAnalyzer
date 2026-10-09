"""Explicit financial research priority, with verified live freshness gates.

Fixed user policy, not a calibrated return model. Unknown factors retain their
weight and contribute no points; they never become zero-valued financial facts.
"""

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from math import isfinite

from .earnings_catalysts import catalyst_adjustment
from .financial_quality import MAX_TTM_AGE_DAYS
from .analyst_consensus import load_snapshots, consensus_score
from .observations import close_cutoff, available as observed_available, member_asof

POLICY_VERSION="financial-analyst-priority-v3"
SIGNAL_VERSION="weekly-signal-v8-bank-event-risk"
WEIGHTS={"financial":.45,"technical":.35,"analyst":.10,"earnings":.10}
MAX_AUDIT_AGE_HOURS=48
MIN_FACTOR_COVERAGE=.80
MIN_PEERS=5
MIN_FINANCIAL_SCORE=50
MIN_TOTAL_SCORE=55
GENERAL_FACTORS={
    "revenue_growth":.125,"eps_growth":.125,
    "operating_margin":.125,"net_margin":.075,"operating_margin_change":.05,
    "fcf_margin":.10,"cash_conversion":.05,"net_debt_to_fcf":.10,
    "earnings_yield":.125,"fcf_yield":.125,
}
# Cash flow and debt have different meanings for banks/insurers. This limited
# profile scores growth, reported profitability and earnings valuation only.
FINANCIAL_FACTORS={"revenue_growth":.15,"eps_growth":.20,
                   "net_margin":.15,"net_margin_change":.10,"earnings_yield":.40}
BANK_FACTORS={"revenue_growth":.10,"eps_growth":.15,"net_margin":.10,
              "earnings_yield":.25,"return_on_equity":.25,"cet1_ratio":.15}
METRIC_COLUMNS="company_id,period_end,filed_date,revenue,net_income,eps_diluted,operating_income,free_cash_flow,cash,total_debt,shares_outstanding,supplemental"


def number(value):
    try:
        result=float(value)
        return result if isfinite(result) else None
    except (TypeError,ValueError):
        return None


def ratio(a,b):
    a=number(a); b=number(b)
    return a/b if a is not None and b is not None and b>0 else None


def paged(factory):
    rows=[]; start=0
    while True:
        page=factory(start,start+999).execute().data or []
        rows.extend(page)
        if len(page)<1000:
            return rows
        start+=1000


def load_inputs(db,asof=None,analyst_history=False,point_in_time=False):
    companies={r["id"]:r for r in (db.table("companies")
               .select("id,ticker,sector,industry,scoring_profile,is_sp500").execute().data or [])}
    if not point_in_time:
        companies={cid:r for cid,r in companies.items() if r.get("is_sp500")}
    def query(a,b):
        q=db.table("financial_metrics").select(METRIC_COLUMNS).eq("period_type","ttm")
        if asof:
            q=q.gte("period_end",(date.fromisoformat(asof)-timedelta(days=640)).isoformat()).lte("filed_date",asof)
        return q.order("company_id").order("period_end",desc=True).order("filed_date",desc=True).range(a,b)
    if point_in_time:
        versions=paged(lambda a,b:db.table("financial_metric_versions").select("company_id,period_end,observed_at,provenance,snapshot")
                       .eq("period_type","ttm").order("company_id").order("observed_at").range(a,b))
        metrics=[{**v["snapshot"],"observed_at":v["observed_at"],"provenance":v["provenance"]} for v in versions]
        memberships=paged(lambda a,b:db.table("index_memberships").select("company_id,effective_from,effective_to,captured_at")
                          .eq("index_code","SP500").order("id").range(a,b))
    else:
        metrics=paged(query); memberships=[]
    earnings_observations=paged(lambda a,b:db.table("earnings_event_versions").select("event_id,company_id,observed_at,snapshot")
                               .order("observed_at").range(a,b)) if point_in_time else []
    by_company=defaultdict(list)
    for row in metrics:
        if row.get("filed_date") and row["company_id"] in companies:
            by_company[row["company_id"]].append(row)
    runs=(db.table("pipeline_runs").select("metadata,status")
          .eq("pipeline","research_sources_refresh").order("started_at",desc=True).limit(5).execute().data or [])
    audit=next(((r.get("metadata") or {}).get("financial_audit") for r in runs
                if (r.get("metadata") or {}).get("financial_audit")),{})
    snapshots=load_snapshots(db,None if analyst_history else (datetime.now(timezone.utc)-timedelta(days=8)).isoformat())
    analyst_rows=defaultdict(list)
    for row in snapshots:
        analyst_rows[row["company_id"]].append(row)
    return {"companies":companies,"metrics":dict(by_company),"audit":audit,"analyst_snapshots":dict(analyst_rows),
            "point_in_time":point_in_time,"memberships":memberships,"earnings_observations":earnings_observations,
            "first_earnings_observation":min((r["observed_at"] for r in earnings_observations),default=None),
            "first_observed_at":min((r["observed_at"] for r in metrics),default=None) if point_in_time else None}


def verify_audit(audit,now=None):
    now=now or datetime.now(timezone.utc)
    if audit.get("scope")!="full_universe" or not audit.get("finished_at"):
        raise RuntimeError("Financial ranking requires a full SEC freshness audit")
    try:
        checked=datetime.fromisoformat(audit["finished_at"].replace("Z","+00:00"))
        age=(now-checked).total_seconds()/3600
    except (ValueError,TypeError):
        raise RuntimeError("Financial audit timestamp is invalid")
    if not 0<=age<=MAX_AUDIT_AGE_HOURS:
        raise RuntimeError(f"Financial audit is older than {MAX_AUDIT_AGE_HOURS} hours; refresh SEC before selection")
    entries={r["company_id"]:r for r in audit.get("companies",[])}
    if len(entries)!=audit.get("summary",{}).get("universe_checked"):
        raise RuntimeError("Financial audit company coverage is inconsistent")
    return entries


def financial_snapshot(rows,asof,audit_entry=None,live=True,point_in_time=False):
    available=[r for r in rows if r.get("filed_date") and r["filed_date"]<=asof and r["period_end"]<=asof]
    if point_in_time:
        available=[r for r in available if observed_available(r,close_cutoff(asof))]
    if not available:
        return None,"no_available_ttm"
    latest=max(available,key=lambda r:(r["period_end"],r.get("observed_at") or "",r["filed_date"]))
    age=(date.fromisoformat(asof)-date.fromisoformat(latest["period_end"])).days
    if not 0<=age<=MAX_TTM_AGE_DAYS:
        return None,"old_ttm_period"
    if live:
        entry=audit_entry or {}
        if entry.get("status")!="current":
            return None,"filing_not_verified"
        report=entry.get("latest_report") or {}
        if (latest["period_end"]!=entry.get("ttm_period") or not report.get("period_end")
                or latest["period_end"]<report["period_end"]
                or (report.get("filed_date") or "9999")>asof
                or latest["filed_date"]<(entry.get("ttm_filed_date") or "9999")):
            return None,"ttm_does_not_match_verified_filing"
    if any(number(latest.get(k)) is None for k in ("revenue","net_income","eps_diluted")):
        return None,"missing_core_financials"
    if number(latest.get("revenue"))<=0:
        return None,"invalid_revenue"
    end=date.fromisoformat(latest["period_end"])
    previous=[r for r in available if 300<=(end-date.fromisoformat(r["period_end"])).days<=450]
    prior=min(previous,key=lambda r:(abs((end-date.fromisoformat(r["period_end"])).days-365),
                                   -(datetime.fromisoformat(r["observed_at"]).timestamp() if r.get("observed_at") else date.fromisoformat(r["filed_date"]).toordinal())),default=None)
    return {"latest":latest,"previous":prior,"period_age_days":age},None


def factors(snapshot,price):
    cur=snapshot["latest"]; prev=snapshot.get("previous") or {}
    rev=number(cur.get("revenue")); eps=number(cur.get("eps_diluted")); fcf=number(cur.get("free_cash_flow"))
    old_rev=number(prev.get("revenue")); old_eps=number(prev.get("eps_diluted"))
    op_margin=ratio(cur.get("operating_income"),rev); net_margin=ratio(cur.get("net_income"),rev)
    old_op=ratio(prev.get("operating_income"),old_rev); old_net=ratio(prev.get("net_income"),old_rev)
    shares=number(cur.get("shares_outstanding")); debt=number(cur.get("total_debt")); cash=number(cur.get("cash"))
    if (cur.get("supplemental") or {}).get("debt_basis")=="long_term_debt_proxy":
        debt=None
    market_cap=price*shares if shares is not None and shares>0 else None
    equity=number((cur.get("supplemental") or {}).get("equity",{}).get("value"))
    old_equity=number((prev.get("supplemental") or {}).get("equity",{}).get("value"))
    average_equity=(equity+old_equity)/2 if equity is not None and old_equity is not None and equity>0 and old_equity>0 else None
    return {
        "revenue_growth":rev/old_rev-1 if rev is not None and old_rev is not None and old_rev>0 else None,
        "eps_growth":(eps-old_eps)/abs(old_eps) if eps is not None and old_eps not in (None,0) else None,
        "operating_margin":op_margin,"net_margin":net_margin,
        "operating_margin_change":op_margin-old_op if op_margin is not None and old_op is not None else None,
        "net_margin_change":net_margin-old_net if net_margin is not None and old_net is not None else None,
        "fcf_margin":ratio(fcf,rev),"cash_conversion":ratio(fcf,cur.get("net_income")),
        "net_debt_to_fcf":(debt-cash)/fcf if debt is not None and cash is not None and fcf is not None and fcf>0 else None,
        # Negative EPS is a negative yield, never a cheap negative P/E.
        "earnings_yield":ratio(eps,price),"fcf_yield":ratio(fcf,market_cap),
        "return_on_equity":ratio(cur.get("net_income"),average_equity),
        "cet1_ratio":number((cur.get("supplemental") or {}).get("cet1_ratio",{}).get("value")),
    }


def finance_profile(company):
    if company.get("scoring_profile")=="bank" or company.get("industry") in ("Diversified Banks","Regional Banks"):
        return "bank"
    return "financial" if (company.get("scoring_profile")=="bank" or
                           "financial" in (company.get("sector") or "").lower()) else "general"


def financial_scores(candidates,inputs,asof,live=True,now=None):
    entries=verify_audit(inputs.get("audit") or {},now) if live else {}
    scored={}; rejected={}; peer_values=defaultdict(list)
    for candidate in candidates:
        cid=candidate["company_id"]; company=inputs["companies"].get(cid)
        price=number(candidate.get("current_price"))
        if not company or price is None or price<=0:
            rejected[cid]="missing_company_or_price"; continue
        if inputs.get("point_in_time") and not member_asof(inputs.get("memberships",[]),cid,asof):
            rejected[cid]="membership_not_observed"; continue
        snapshot,error=financial_snapshot(inputs["metrics"].get(cid,[]),asof,entries.get(cid),live,inputs.get("point_in_time",False))
        if error:
            rejected[cid]=error; continue
        profile=finance_profile(company); weights=BANK_FACTORS if profile=="bank" else FINANCIAL_FACTORS if profile=="financial" else GENERAL_FACTORS
        values=factors(snapshot,price)
        coverage=sum(weight for key,weight in weights.items() if values.get(key) is not None)
        if coverage+1e-9<MIN_FACTOR_COVERAGE:
            rejected[cid]="insufficient_financial_factor_coverage"; continue
        sector=company.get("sector")
        if not sector:
            rejected[cid]="missing_sector"; continue
        scored[cid]={"profile":profile,"sector":sector,"coverage":coverage,"values":values,"snapshot":snapshot,"weights":weights}
        for key in weights:
            if values.get(key) is not None:
                peer_values[(sector,profile,key)].append(values[key])
    for values in peer_values.values():
        values.sort()
    result={}
    for cid,item in scored.items():
        breakdown={}; total=0.; coverage=0.
        for key,weight in item["weights"].items():
            value=item["values"].get(key); peers=peer_values[(item["sector"],item["profile"],key)]
            percentile=None
            if value is not None and len(peers)>=MIN_PEERS:
                percentile=100*(bisect_left(peers,value)+(bisect_right(peers,value)-bisect_left(peers,value))/2)/len(peers)
                if key=="net_debt_to_fcf":
                    percentile=100-percentile
                coverage+=weight
                total+=weight*percentile
            breakdown[key]={"value":value,"score":percentile,"weight":weight,"peers":len(peers),
                            "contribution":0. if percentile is None else weight*percentile}
        if coverage+1e-9<MIN_FACTOR_COVERAGE:
            rejected[cid]="insufficient_sector_peer_coverage"; continue
        snapshot=item["snapshot"]; latest=snapshot["latest"]
        result[cid]={"score":round(total,4),"coverage":round(coverage,4),"profile":item["profile"],
                     "period_end":latest["period_end"],"filed_date":latest["filed_date"],
                     "period_age_days":snapshot["period_age_days"],"previous_period":(snapshot.get("previous") or {}).get("period_end"),
                     "audit_checked_at":(inputs.get("audit") or {}).get("finished_at") if live else None,
                     "freshness_mode":"verified_latest_filing" if live else "observed_point_in_time" if inputs.get("point_in_time") else "historical_filing_date_proxy",
                     "factors":breakdown,"missing_factors":[k for k,b in breakdown.items() if b["score"] is None]}
    return result,rejected


def rank_candidates(candidates,inputs,asof,earnings=None,live=True,now=None,top=5,upcoming=None):
    financial,rejected=financial_scores(candidates,inputs,asof,live,now)
    picks=[]; earnings=earnings or {}; analyst_status=Counter()
    decision_at=now or datetime.now(timezone.utc)
    for row in candidates:
        cid=row["company_id"]; data=financial.get(cid)
        if data is None:
            continue
        future=(upcoming or {}).get(cid) or {}
        if 5 in future.get("within_execution_horizons",future.get("within_horizons",[])):
            rejected[cid]="earnings_within_primary_horizon"; continue
        technical=number(row.get("opportunity_score"))
        if technical is None or (number(row.get("setup_sample_size")) or 0)<50:
            rejected[cid]="insufficient_price_setup_history"; continue
        if data["score"]<MIN_FINANCIAL_SCORE:
            rejected[cid]="financial_score_below_minimum"; continue
        technical=max(0.,min(100.,technical))
        event=earnings.get(cid) or {}
        catalyst=50+6.25*catalyst_adjustment(event)
        analyst=consensus_score(inputs.get("analyst_snapshots",{}).get(cid,[]),asof,live=live,now=decision_at)
        analyst_status[analyst["status"]]+=1
        contributions={"financial":WEIGHTS["financial"]*data["score"],
                       "technical":WEIGHTS["technical"]*technical,"earnings":WEIGHTS["earnings"]*catalyst,
                       "analyst":WEIGHTS["analyst"]*analyst["score"]}
        total=sum(contributions.values())
        if total<MIN_TOTAL_SCORE:
            rejected[cid]="combined_score_below_minimum"; continue
        picks.append({"row":row,"financial":data,"score":round(total,4),"technical_score":technical,
                      "earnings_score":catalyst,"earnings_available":any(event.get(k) is not None for k in ("surprise_percent","revenue_surprise_percent")),
                      "contributions":contributions,"catalyst":event,"analyst":analyst})
    picks.sort(key=lambda p:(-p["score"],str(p["row"]["company_id"])))
    limit=len(picks) if top is None else min(top,5)
    return picks[:limit],{"policy_version":POLICY_VERSION,"weights":WEIGHTS,
                              "price_date":asof,"candidates":len(candidates),"financial_eligible":len(financial),
                              "ranking_eligible":len(picks),"selected":min(len(picks),limit),
                              "rejected":dict(Counter(rejected.values())),
                              "audit_checked_at":(inputs.get("audit") or {}).get("finished_at"),
                              "decision_at":decision_at.isoformat(),"analyst_status":dict(analyst_status),
                              "validated_forecast":False}
