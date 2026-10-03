from fastapi import APIRouter, HTTPException
from ..db.client import get_supabase
from ..research.analyst import build as build_analyst_assessment
from ..research.fundamentals import derive as derive_fundamentals
from ..research.earnings_catalysts import catalyst_adjustment, recent_earnings
from ..research.validation_gate import validated_horizons
from ..research.signal_history import complete_oldest_signal_cohort
from ..research.current_valuation import current_valuations
from ..research.financial_ranking import load_inputs, rank_candidates, WEIGHTS, POLICY_VERSION
from ..research.analyst_consensus import load_snapshots, consensus_score
from datetime import datetime,timezone,timedelta
from ..research.weekly_rank_metrics import RANKER_VERSION, ranker_is_validated
from .retry_clock_skew import RetryClockSkewRoute

router=APIRouter(prefix="/api/v1/research",tags=["research"],route_class=RetryClockSkewRoute)

@router.get("/candidates")
def candidates():
    db=get_supabase()
    rows=db.rpc("research_dashboard_candidates").execute().data or []
    earnings=recent_earnings(db,rows)
    valuations=current_valuations(db,rows)
    result=[{"ticker":r["ticker"],"company":r["company"],"sector":r.get("sector"),"signal":"setup","score":r.get("research_priority_score"),"coverage":r.get("research_priority_coverage"),"catalyst":r.get("research_priority_reason"),"fundamentals":r.get("fundamentals_score"),"valuation":r.get("valuation_score"),"earnings":r.get("earnings_score"),"pe":valuations.get(r["company_id"],{}).get("pe"),"price_to_fcf":valuations.get(r["company_id"],{}).get("price_to_fcf"),"as_of_date":r.get("as_of_date"),"opportunity_score":r.get("opportunity_score"),"setup_probability_up":r.get("setup_probability_up"),"setup_median_return_5d":r.get("setup_median_return_5d"),"setup_sample_size":r.get("setup_sample_size"),"upside_to_60d_high":r.get("upside_to_60d_high"),"setup_drawdown_60d":r.get("setup_drawdown_60d"),"opportunity_reason":r.get("opportunity_reason"),"current_price":r.get("current_price"),"price_date":r.get("price_date"),"price_source":r.get("price_source"),"earnings_catalyst":earnings.get(r.get("company_id"))} for r in rows]
    signal_date=max((str(r.get("price_date") or "") for r in rows),default="")
    current=[r for r in rows if r.get("price_date")==signal_date and r.get("as_of_date")==signal_date]
    ranking={}; ranking_error=None
    inputs=load_inputs(db,signal_date)
    try:
        picks,summary=rank_candidates(current,inputs,signal_date,earnings,top=None)
        ranking={p["row"]["ticker"]:p for p in picks}
    except RuntimeError as exc:
        ranking_error=str(exc)
    for x in result:
        p=ranking.get(x["ticker"])
        cid=next(r["company_id"] for r in rows if r["ticker"]==x["ticker"])
        x["analyst_consensus"]=consensus_score(inputs.get("analyst_snapshots",{}).get(cid,[]),signal_date)
        x["catalyst_adjustment"]=round(catalyst_adjustment(x.get("earnings_catalyst")),2)
        x["research_rank_score"]=p["score"] if p else None
        x["financial_ranking"]=p["financial"] if p else None
        x["ranking_weights"]=WEIGHTS
        x["financial_ranking_status"]="eligible" if p else (ranking_error or "Does not meet freshness, financial coverage or score requirements")
    result.sort(key=lambda x:x.get("research_rank_score") if x.get("research_rank_score") is not None else -999,reverse=True)
    return result

@router.get("/data-audit")
def data_audit():
    db=get_supabase(); d=db.rpc("research_data_audit").execute().data or {}; total=d.get("universe",0)
    def item(key,label):
        count=d.get(key,0); pct=round(100*count/total,1) if total else 0
        return {"key":key,"label":label,"companies":count,"total":total,"coverage_pct":pct,"status":"strong" if pct>=95 else "partial"}
    layers=[item("prices","Daily prices"),item("features","Price features"),item("setups","Current setup metrics"),item("fundamentals","Fundamentals"),item("valuation","Valuation"),item("estimates","Analyst estimates"),item("earnings","Historical earnings events")]
    snapshots=load_snapshots(db,(datetime.now(timezone.utc)-timedelta(days=8)).isoformat())
    universe_ids={r["id"] for r in db.table("companies").select("id").eq("is_sp500",True).execute().data or []}
    grouped={}
    for row in snapshots:
        if row["company_id"] in universe_ids:
            grouped.setdefault(row["company_id"],[]).append(row)
    count=sum(consensus_score(history,datetime.now(timezone.utc).date().isoformat())["available"] for history in grouped.values())
    layers.append({"key":"analyst_consensus","label":"Current analyst recommendations","companies":count,"total":total,
                   "coverage_pct":round(100*count/total,1) if total else 0,"status":"strong" if total and count>=total*.95 else "partial"})
    notes=["Company counts show coverage, not filing freshness, field completeness, or predictive value."]
    if d.get("estimates",0)<total*.95:
        notes.append("Analyst estimate coverage is limited; rankings do not assume missing estimates are zero.")
    reports=(db.table("pipeline_runs").select("metadata,finished_at,status")
             .eq("pipeline","research_sources_refresh").order("started_at",desc=True).limit(3).execute().data or [])
    report=next((r for r in reports if (r.get("metadata") or {}).get("financial_audit")),None)
    financial=((report.get("metadata") or {}).get("financial_audit") or {}) if report else {}
    if financial:
        notes.append("Financial freshness is checked against SEC filing periods; retrieval success does not imply complete data.")
    return {"universe":total,"layers":layers,"missing_price_tickers":d.get("missing_price_tickers",[]),"notes":notes,
            "financial_quality":financial.get("summary"),"financial_checked_at":financial.get("finished_at"),
            "financial_gaps":[r for r in financial.get("companies",[]) if r.get("status")!="current" or r.get("missing_fields")]}

@router.get("/companies-search")
def companies_search(q:str=""):
    q=q.strip()
    if not q: return []
    db=get_supabase(); ticker_rows=db.table("companies").select("ticker,name,sector").eq("is_sp500",True).ilike("ticker",f"%{q}%").limit(8).execute().data or []; name_rows=db.table("companies").select("ticker,name,sector").eq("is_sp500",True).ilike("name",f"%{q}%").limit(8).execute().data or []
    seen=set(); rows=[]
    for x in ticker_rows+name_rows:
        if x["ticker"] in seen: continue
        seen.add(x["ticker"]); rows.append({"ticker":x["ticker"],"company":x["name"],"sector":x.get("sector")})
    return rows[:8]

@router.get("/companies/{ticker}")
def company(ticker:str):
    db=get_supabase(); companies=db.table("companies").select("*").eq("ticker",ticker.upper()).limit(1).execute().data or []
    if not companies: raise HTTPException(404,"Company not found")
    c=companies[0]; snapshots=db.table("research_snapshots").select("*").eq("company_id",c["id"]).order("as_of_date",desc=True).limit(12).execute().data or []
    latest_earnings=(db.table("earnings_events").select("reported_date,event_time,surprise_percent,revenue_surprise_percent,source").eq("company_id",c["id"]).eq("source","massive_benzinga").lte("reported_date",__import__("datetime").date.today().isoformat()).order("reported_date",desc=True).limit(1).execute().data or []); latest_earnings=latest_earnings[0] if latest_earnings else None
    financials=(db.table("financial_metrics").select("period_end,revenue,operating_income,net_income,eps_diluted,free_cash_flow,capex,cash,total_debt,source").eq("company_id",c["id"]).eq("period_type","annual").order("period_end",desc=True).limit(6).execute().data or [])
    usable=[x for x in financials if x.get("revenue") is not None]; fundamental_signals=None
    if usable:
        sig=derive_fundamentals(usable[0],usable[1] if len(usable)>1 else None); fundamental_signals={**sig.__dict__,"period_end":usable[0].get("period_end"),"source":usable[0].get("source")}
    assessment=build_analyst_assessment(snapshots[0],latest_earnings,fundamental_signals).__dict__ if snapshots else None
    consensus=(db.table("analyst_consensus_snapshots").select("*").eq("company_id",c["id"]).order("observed_at",desc=True).order("period_date",desc=True).limit(40).execute().data or [])
    return {"company":c,"snapshots":snapshots,"financials":financials,"analyst_assessment":assessment,
            "analyst_consensus":consensus_score(consensus,datetime.now(timezone.utc).date().isoformat())}

@router.get("/framework")
def framework(): return {"dimensions":["fundamentals","valuation","earnings/revisions","momentum","news/sentiment","catalysts"],"purpose":"Prioritize companies for research; not personalized buy/sell instructions."}

@router.get("/signals")
def signals(limit:int=100):
    db=get_supabase(); rows=(db.table("research_predictions").select("*,companies(ticker,name,sector)").order("signal_date",desc=True).order("rank").limit(min(max(limit,1),500)).execute().data or [])
    rows=complete_oldest_signal_cohort(db,rows)
    ids=list({x.get("company_id") for x in rows if x.get("company_id")}); latest={}
    if ids:
        prices=(db.table("price_history").select("company_id,price_date,close").in_("company_id",ids).order("price_date",desc=True).execute().data or [])
        for p in prices: latest.setdefault(p["company_id"],p)
    for x in rows:
        p=latest.get(x.get("company_id")); x["current_price"]=p.get("close") if p else None; x["current_price_date"]=p.get("price_date") if p else None
        entry=x.get("entry_price")
        x["return_since_signal"]=(float(x["current_price"])/float(entry)-1) if p and entry not in (None,0) else None
    return rows

@router.get("/scorecard")
def scorecard():
    db=get_supabase(); rows=(db.table("research_predictions").select("horizon_days,actual_return,benchmark_return,excess_return,correct_direction,evaluated_at,model_version").execute().data or []); rows=[x for x in rows if x.get("evaluated_at")]
    import statistics
    def stats(xs):
        n=len(xs)
        if not n:return {"evaluated":0,"win_rate":None,"avg_return":None,"median_return":None,"avg_excess_return":None,"beat_spy_rate":None}
        rets=[float(x["actual_return"]) for x in xs if x.get("actual_return") is not None]; excess=[float(x["excess_return"]) for x in xs if x.get("excess_return") is not None]
        return {"evaluated":n,"win_rate":sum(bool(x.get("correct_direction")) for x in xs)/n,"avg_return":sum(rets)/len(rets) if rets else None,"median_return":statistics.median(rets) if rets else None,"avg_excess_return":sum(excess)/len(excess) if excess else None,"beat_spy_rate":sum(x>0 for x in excess)/len(excess) if excess else None}
    versions=sorted({x.get("model_version") or "unknown" for x in rows})
    return {
        "overall":stats(rows),
        "by_horizon":{str(h):stats([x for x in rows if x.get("horizon_days")==h]) for h in (5,10,20)},
        "by_model":{
            v:{
                "overall":stats([x for x in rows if (x.get("model_version") or "unknown")==v]),
                "by_horizon":{str(h):stats([x for x in rows if (x.get("model_version") or "unknown")==v and x.get("horizon_days")==h]) for h in (5,10,20)}
            } for v in versions
        }
    }

@router.get("/system-health")
def system_health():
    db=get_supabase()
    runs=(db.table("pipeline_runs").select("*").eq("pipeline","daily_market_research").order("started_at",desc=True).limit(1).execute().data or [])
    source_runs=(db.table("pipeline_runs").select("*").eq("pipeline","research_sources_refresh").order("started_at",desc=True).limit(1).execute().data or [])
    model_runs=(db.table("model_validation_runs").select("finished_at,status,model_version,best_stage,best_groups,error_message,results").neq("model_version",RANKER_VERSION).order("started_at",desc=True).limit(1).execute().data or [])
    ranker_runs=(db.table("model_validation_runs").select("finished_at,status,model_version,best_stage,error_message,results").eq("model_version",RANKER_VERSION).order("started_at",desc=True).limit(1).execute().data or [])
    finance_runs=(db.table("pipeline_runs").select("finished_at,status,metadata")
                  .eq("pipeline","weekly_financial_comparison").order("started_at",desc=True).limit(1).execute().data or [])
    analyst_runs=(db.table("pipeline_runs").select("finished_at,status,metadata")
                  .eq("pipeline","analyst_consensus_refresh").order("started_at",desc=True).limit(1).execute().data or [])
    latest=(db.table("price_history").select("price_date").order("price_date",desc=True).limit(1).execute().data or [])
    feature=(db.table("price_features").select("feature_date").order("feature_date",desc=True).limit(1).execute().data or [])
    audit=db.rpc("research_data_audit").execute().data or {}
    run=runs[0] if runs else None
    source_run=source_runs[0] if source_runs else None
    model_run=model_runs[0] if model_runs else None
    if model_run:
        model_run["validated_horizons"]=list(validated_horizons(model_run))
        model_run.pop("results",None)
    ranker_run=ranker_runs[0] if ranker_runs else None
    if ranker_run:
        report=ranker_run.pop("results",None) or {}
        ranker_run["promotion_passed"]=ranker_is_validated({**ranker_run,"results":report})
        ranker_run["selection"]=report.get("selection")
        ranker_run["holdout"]=report.get("holdout")
    return {
        "status":run.get("status") if run else "not_run",
        "last_run":run,
        "latest_price_date":latest[0]["price_date"] if latest else None,
        "latest_feature_date":feature[0]["feature_date"] if feature else None,
        "research_sources_run":source_run,
        "model_validation":model_run,
        "weekly_ranker_validation":ranker_run,
        "analyst_consensus_refresh":analyst_runs[0] if analyst_runs else None,
        "financial_ranking_policy":{"version":POLICY_VERSION,"weights":WEIGHTS,"validated_forecast":False,
                                    "comparison":finance_runs[0] if finance_runs else None},
        "coverage":{
            "universe":audit.get("universe",0),
            "fundamentals":audit.get("fundamentals",0),
            "earnings":audit.get("earnings",0),
            "valuation":audit.get("valuation",0),
            "estimates":audit.get("estimates",0),
        },
    }
