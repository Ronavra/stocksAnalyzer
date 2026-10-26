from fastapi import APIRouter, HTTPException
from ..db.client import get_supabase
from ..research.analyst import build as build_analyst_assessment
from ..research.fundamentals import derive as derive_fundamentals
from ..research.earnings_catalysts import catalyst_adjustment, recent_earnings, upcoming_earnings
from ..research.news import news_summary
from ..research.validation_gate import validated_horizons
from ..research.signal_history import complete_oldest_signal_cohort
from ..research.signal_prices import load_price_timelines
from ..research.current_valuation import current_valuations
from ..research.financial_ranking import load_inputs, rank_candidates, WEIGHTS, POLICY_VERSION, finance_profile
from ..research.analyst_consensus import load_snapshots, consensus_score
from datetime import datetime,timezone,timedelta
from ..research.weekly_rank_metrics import RANKER_VERSION, ranker_is_validated
from .retry_clock_skew import RetryClockSkewRoute
from ..research.prospective_metrics import prospective_metrics, paged
from ..research.portfolio_comparison import load_portfolio_comparison
from ..market_calendar import latest_completed_session, NY
from ..research.daily_schedule import schedule_status
from ..research.market_freshness import market_freshness
from ..research.model_identity import MODEL_VERSION
from ..research.source_coverage import load_coverage, coverage_from_inventory

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
    upcoming=upcoming_earnings(db,current,signal_date)
    ranking={}; ranking_error=None
    inputs=load_inputs(db,signal_date)
    try:
        picks,summary=rank_candidates(current,inputs,signal_date,earnings,top=None,upcoming=upcoming)
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
        x["upcoming_earnings"]=upcoming.get(cid)
        x["earnings_risk_excluded"]=5 in (upcoming.get(cid) or {}).get("within_execution_horizons",[])
        x["financial_ranking_status"]="eligible" if p else ("Earnings calendar unavailable or stale; excluded from live selection" if (upcoming.get(cid) or {}).get("calendar_status") != "current" else ranking_error or "Does not meet freshness, financial coverage or score requirements")
    result.sort(key=lambda x:x.get("research_rank_score") if x.get("research_rank_score") is not None else -999,reverse=True)
    return result

def _cached_data_audit(db):
    """Serve a clearly labeled last successful coverage snapshot on timeout."""
    rows=(db.table("pipeline_runs").select("metadata,finished_at,status")
          .eq("pipeline","source_coverage_audit").eq("status","success")
          .order("started_at",desc=True).limit(1).execute().data or [])
    if not rows or not isinstance((rows[0].get("metadata") or {}).get("families"),list):
        raise HTTPException(status_code=503,detail="Data audit timed out; no cached coverage is available")
    row=rows[0]
    families=row["metadata"]["families"]
    total=max((int(f.get("total") or 0) for f in families),default=0)
    layers=[{"key":f.get("key"),"label":f.get("label"),"companies":f.get("covered_companies"),
             "total":f.get("total"),"coverage_pct":round(100*(f.get("covered_companies") or 0)/f["total"],1)
               if f.get("total") else None,"status":"cached"} for f in families]
    return {"universe":total,"layers":layers,"missing_price_tickers":[],
            "notes":["Live audit exceeded database statement timeout.",
                     "Last successful coverage snapshot shown; company-level gaps unavailable.",
                     "Cached coverage does not prove freshness or predictive value."],
            "source_families":families,"source_checks":[],"all_major_data_complete":False,
            "company_gaps":[],"financial_quality":None,"financial_checked_at":None,
            "financial_gaps":[],"data_status":"cached_after_timeout",
            "snapshot_finished_at":row.get("finished_at")}


@router.get("/data-audit")
def data_audit():
    from postgrest.exceptions import APIError
    db=get_supabase()
    try:
        snapshot=db.rpc("research_dashboard_data_audit").execute().data or {}
    except APIError as exc:
        if str(getattr(exc,"code",None)) != "57014":
            raise
        return _cached_data_audit(db)
    d=snapshot.get("audit") or {}; total=d.get("universe",0)
    counts=snapshot.get("counts") or {}
    def item(key,label,observed=False):
        count=counts.get(key,d.get(key,0)); pct=round(100*count/total,1) if total else 0
        return {"key":key,"label":label,"companies":count,"total":total,"coverage_pct":pct,
                "status":"observed" if observed else "strong" if pct>=95 else "partial"}
    layers=[item("prices","Daily prices"),item("features","Price features"),item("setups","Current setup metrics"),
            item("fundamentals","Fundamentals"),item("valuation","Valuation"),item("earnings","Historical earnings events"),
            item("upcoming_eps_consensus","Upcoming earnings EPS consensus · 120 days"),
            item("disclosures","SEC disclosures · past 90 days",True),item("corporate_guidance_events","Corporate guidance"),
            item("news_events","News articles"),item("analyst_consensus","Current analyst recommendations")]
    report=snapshot.get("financial_report") or {}
    financial=(report.get("metadata") or {}).get("financial_audit") or {}
    coverage=coverage_from_inventory(snapshot.get("inventory") or [],snapshot.get("calendars") or [],
                                     report,snapshot.get("source_checks") or [])
    estimate_family=next((f for f in coverage["families"] if f["key"]=="estimates"),{})
    counts["estimates"]=estimate_family.get("covered_companies",0)
    layers.append(item("estimates","Current fiscal EPS / revenue estimates"))
    notes=["Company counts show coverage, not filing freshness, field completeness, or predictive value.",
           "Free calendar freshness and missing dates are audited separately from stored upcoming EPS estimates. Unknown calendars block live selection.",
           "News sentiment is attributed to the provider. SEC guidance uses explicit ranges; unparsed releases remain unknown.",
           "Fiscal estimates and financial statements retain their observation dates; coverage does not establish predictive value."]
    return {"universe":total,"layers":layers,"missing_price_tickers":d.get("missing_price_tickers",[]),"notes":notes,
            "source_families":coverage["families"],"source_checks":coverage["source_checks"],"all_major_data_complete":False,
            "company_gaps":[{"ticker":c["ticker"],"gaps":[{"key":x["key"],"label":x["label"],"status":x["status"]} for x in c["layers"] if x["key"] in c["gaps"]]} for c in coverage["companies"]],
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
    latest_earnings=(db.table("earnings_events").select("reported_date,event_time,surprise_percent,revenue_surprise_percent,source").eq("company_id",c["id"]).in_("source",["massive_benzinga","alphavantage","yahoo_finance"]).lte("reported_date",__import__("datetime").date.today().isoformat()).order("reported_date",desc=True).limit(1).execute().data or []); latest_earnings=latest_earnings[0] if latest_earnings else None
    financials=(db.table("financial_metrics").select("period_end,revenue,operating_income,net_income,eps_diluted,free_cash_flow,capex,cash,total_debt,source").eq("company_id",c["id"]).eq("period_type","annual").order("period_end",desc=True).limit(6).execute().data or [])
    usable=[x for x in financials if x.get("revenue") is not None]; fundamental_signals=None
    if usable:
        sig=derive_fundamentals(usable[0],usable[1] if len(usable)>1 else None); fundamental_signals={**sig.__dict__,"period_end":usable[0].get("period_end"),"source":usable[0].get("source")}
    assessment=build_analyst_assessment(snapshots[0],latest_earnings,fundamental_signals).__dict__ if snapshots else None
    consensus=(db.table("analyst_consensus_snapshots").select("*").eq("company_id",c["id"]).order("observed_at",desc=True).order("period_date",desc=True).limit(40).execute().data or [])
    disclosures=(db.table("company_disclosures").select("form,filing_date,published_at,observed_at,headline,source_url,items")
                 .eq("company_id",c["id"]).order("published_at",desc=True).limit(10).execute().data or [])
    news=(db.table("news_events").select("headline,published_at,created_at,source_url,publisher,sentiment,sentiment_method,why_it_matters")
          .eq("company_id",c["id"]).order("published_at",desc=True).limit(20).execute().data or [])
    guidance=(db.table("corporate_guidance_events").select("event_date,fiscal_year,fiscal_period,eps_method,revenue_method,eps_guidance_low,eps_guidance_high,revenue_guidance_low,revenue_guidance_high,source,source_url,captured_at,evidence")
              .eq("company_id",c["id"]).order("event_date",desc=True).limit(15).execute().data or [])
    estimate_snapshots=(db.table("estimate_snapshots").select("fiscal_period_end,period_type,relative_period,eps_consensus,eps_low,eps_high,eps_analyst_count,revenue_consensus,revenue_low,revenue_high,revenue_analyst_count,eps_basis,eps_currency,revenue_currency,source,captured_at,captured_date")
                        .eq("company_id",c["id"]).order("captured_at",desc=True).limit(32).execute().data or [])
    source_coverage=load_coverage(db,company_id=c["id"])
    documents=(db.table('research_documents').select('id,kind,title,source,source_url,published_at,observed_at,truncated').eq('company_id',c['id']).order('observed_at',desc=True).limit(20).execute().data or [])
    evidence=(db.table('research_evidence_events').select('id,kind,event_date,published_at,observed_at,source,source_url,payload').eq('company_id',c['id']).order('observed_at',desc=True).limit(40).execute().data or [])
    macro_context=db.rpc('research_macro_context',{}).execute().data
    ttm=(db.table("financial_metrics").select("period_end,filed_date,net_income,supplemental")
         .eq("company_id",c["id"]).eq("period_type","ttm").order("period_end",desc=True).limit(8).execute().data or [])
    bank=None
    if ttm and finance_profile(c)=="bank":
        latest=ttm[0]; old=next((r for r in ttm[1:] if 300<=(datetime.fromisoformat(latest["period_end"])-datetime.fromisoformat(r["period_end"])).days<=450),None)
        equity=(latest.get("supplemental") or {}).get("equity",{}).get("value")
        old_equity=((old or {}).get("supplemental") or {}).get("equity",{}).get("value")
        roe=float(latest["net_income"])/((float(equity)+float(old_equity))/2) if latest.get("net_income") is not None and equity and old_equity and float(equity)>0 and float(old_equity)>0 else None
        bank={"period_end":latest["period_end"],"filed_date":latest["filed_date"],"return_on_equity":roe,
              "roe_basis":"TTM net income / mean beginning and ending shareholders equity","reported":latest.get("supplemental") or {}}
    model=(db.table("model_forecasts").select("feature_date,horizon_days,model_version,validation_run_id,generated_at,probability_up,expected_return,feature_coverage,model_validation_runs!inner(status)")
           .eq("company_id",c["id"]).eq("model_version",MODEL_VERSION)
           .eq("model_validation_runs.status","success")
           .eq("feature_date",latest_completed_session(datetime.now(timezone.utc).astimezone(NY)).isoformat())
           .order("generated_at",desc=True).limit(9).execute().data or [])
    latest_forecasts={}
    for forecast in model:
        forecast.pop("model_validation_runs",None)
        latest_forecasts.setdefault(forecast["horizon_days"],forecast)
    return {"company":c,"snapshots":snapshots,"financials":financials,"analyst_assessment":assessment,"disclosures":disclosures,
            "news":news,"news_summary":news_summary(news),"guidance":guidance,"bank_metrics":bank,
            "estimate_snapshots":estimate_snapshots,"source_checks":source_coverage["source_checks"],"source_coverage":next(iter(source_coverage["companies"]),None),
            'official_documents':documents,'evidence_events':evidence,'macro_context':macro_context,
            "model_forecasts":list(latest_forecasts.values()),
            "analyst_consensus":consensus_score(consensus,datetime.now(timezone.utc).date().isoformat())}

@router.get("/framework")
def framework(): return {"dimensions":["fundamentals","valuation","earnings/revisions","momentum","news/sentiment","catalysts"],"purpose":"Prioritize companies for research; not personalized buy/sell instructions."}

@router.get("/signals")
def signals(limit:int=100):
    db=get_supabase(); rows=(db.table("research_predictions").select("*,companies(ticker,name,sector)").order("signal_date",desc=True).order("rank").limit(min(max(limit,1),500)).execute().data or [])
    rows=complete_oldest_signal_cohort(db,rows)
    return load_price_timelines(db,rows)

@router.get("/cohorts")
def cohorts():
    return paged(get_supabase().table("recommendation_cohorts").select("signal_date,model_version,horizons,expected_picks,status,published_at").order("signal_date",desc=True))

@router.get("/scorecard")
def scorecard():
    db=get_supabase()
    all_rows=paged(db.table("research_predictions").select("id,signal_date,horizon_days,actual_return,benchmark_return,excess_return,correct_direction,evaluated_at,model_version").order("id"))
    cohort_rows=paged(db.table("recommendation_cohorts").select("*").order("signal_date"))
    spy=db.table("companies").select("id").eq("ticker","SPY").limit(1).execute().data or []
    market=paged(db.table("price_history").select("price_date,close,source").eq("company_id",spy[0]["id"])
                 .gte("price_date",min((c["signal_date"] for c in cohort_rows),default=datetime.now(timezone.utc).date().isoformat()))
                 .order("price_date").order("source")) if spy else []
    live=prospective_metrics(cohort_rows,all_rows,market)
    rows=[x for x in all_rows if x.get("evaluated_at")]
    import statistics
    def stats(xs):
        n=len(xs)
        if not n:return {"evaluated":0,"win_rate":None,"avg_return":None,"median_return":None,"avg_excess_return":None,"beat_spy_rate":None}
        rets=[float(x["actual_return"]) for x in xs if x.get("actual_return") is not None]; excess=[float(x["excess_return"]) for x in xs if x.get("excess_return") is not None]
        return {"evaluated":n,"win_rate":sum(bool(x.get("correct_direction")) for x in xs)/n,"avg_return":sum(rets)/len(rets) if rets else None,"median_return":statistics.median(rets) if rets else None,"avg_excess_return":sum(excess)/len(excess) if excess else None,"beat_spy_rate":sum(x>0 for x in excess)/len(excess) if excess else None}
    versions=sorted({x.get("model_version") or "unknown" for x in rows})
    return {
        "prospective":live,
        "overall":stats(rows),
        "by_horizon":{str(h):stats([x for x in rows if x.get("horizon_days")==h]) for h in (5,10,20)},
        "by_model":{
            v:{
                "overall":stats([x for x in rows if (x.get("model_version") or "unknown")==v]),
                "by_horizon":{str(h):stats([x for x in rows if (x.get("model_version") or "unknown")==v and x.get("horizon_days")==h]) for h in (5,10,20)}
            } for v in versions
        }
    }

@router.get("/predictive-readiness")
def predictive_readiness():
    return get_supabase().rpc("research_predictive_readiness").execute().data

@router.get("/active-portfolio")
def active_portfolio():
    from ..research.active_portfolio import load_active_portfolio
    return load_active_portfolio(get_supabase())

@router.get("/portfolio-comparison")
def portfolio_comparison():
    return load_portfolio_comparison(get_supabase())

@router.get("/system-health")
def system_health():
    now=datetime.now(timezone.utc)
    expected=latest_completed_session(now.astimezone(NY)).isoformat()
    snapshot=get_supabase().rpc("research_system_health_snapshot",{
        "p_expected_market_date":expected,"p_ranker_version":RANKER_VERSION,
    }).execute().data
    if not isinstance(snapshot,dict) or not isinstance(snapshot.get("freshness"),dict):
        raise RuntimeError("System health snapshot is incomplete")
    runs=snapshot.get("runs") or {}
    run=runs.get("daily_market_research")
    source_run=runs.get("research_sources_refresh")
    model_run=snapshot.get("model_run")
    ranker_run=snapshot.get("ranker_run")
    finance_run=runs.get("weekly_financial_comparison")
    analyst_run=runs.get("analyst_consensus_refresh")
    enrichment_run=runs.get("research_enrichment")
    deadline_run=runs.get("independent_daily_deadline")
    repair_run=runs.get("research_history_repair")
    audit=snapshot.get("audit") or {}
    finished=(run or {}).get("finished_at")
    schedule=schedule_status(run,now)
    overdue=schedule["overdue"]
    freshness=snapshot["freshness"]
    fresh=freshness["ok"]
    quality=((run or {}).get("metadata") or {}).get("price_session_quality")
    quality_source="daily_market_research"
    quality_checked_at=finished
    if repair_run and repair_run.get("status")=="success" and (repair_run.get("finished_at") or "")>(finished or ""):
        quality=(repair_run.get("metadata") or {}).get("latest_quality")
        quality_source="research_history_repair"
        quality_checked_at=repair_run.get("finished_at")
    if model_run:
        from ..research.model_readiness import execution_status
        model_run=execution_status(model_run,now)
        model_run["validated_horizons"]=list(validated_horizons(model_run))
        model_run.pop("results",None)
    if ranker_run:
        report=ranker_run.pop("results",None) or {}
        ranker_run["promotion_passed"]=ranker_is_validated({**ranker_run,"results":report})
        ranker_run["selection"]=report.get("selection")
        ranker_run["holdout"]=report.get("holdout")
    return {
        "status":"overdue" if overdue else "stale" if run and run.get("status")=="success" and not fresh else run.get("status") if run else "not_run",
        "daily_schedule":schedule,
        "independent_deadline_monitor":deadline_run,
        "research_enrichment":enrichment_run,
        "market_data_current":fresh,"expected_market_date":expected,
        "market_freshness":freshness,
        "price_session_quality":quality,
        "price_session_quality_source":quality_source,"price_session_quality_checked_at":quality_checked_at,
        "last_run":run,
        "latest_price_date":snapshot.get("latest_price_date"),
        "latest_feature_date":snapshot.get("latest_feature_date"),
        "research_sources_run":source_run,
        "model_validation":model_run,
        "model_readiness":snapshot.get("model_readiness"),
        "weekly_ranker_validation":ranker_run,
        "analyst_consensus_refresh":analyst_run,
        "financial_ranking_policy":{"name":"Weekly financial priority","version":POLICY_VERSION,"weights":WEIGHTS,"validated_forecast":False,
                                    "comparison":finance_run},
        "coverage":{
            "universe":audit.get("universe",0),
            "fundamentals":audit.get("fundamentals",0),
            "earnings":audit.get("earnings",0),
            "valuation":audit.get("valuation",0),
            "estimates":(snapshot.get("model_readiness") or {}).get("fiscal_estimate_companies",0),
            "legacy_estimates":audit.get("estimates",0),
        },
    }
