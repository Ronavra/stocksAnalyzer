from fastapi import APIRouter, HTTPException
from ..db.client import get_supabase
from ..research.analyst import build as build_analyst_assessment
from ..research.fundamentals import derive as derive_fundamentals

router=APIRouter(prefix="/api/v1/research",tags=["research"])

@router.get("/candidates")
def candidates():
    db=get_supabase()
    rows=db.rpc("research_dashboard_candidates").execute().data or []
    ids=[r.get("company_id") for r in rows if r.get("company_id")]
    earnings={}
    if ids:
        ev=(db.table("earnings_events").select("company_id,reported_date,surprise_percent,revenue_surprise_percent,source").in_("company_id",ids).eq("source","massive_benzinga").lte("reported_date",__import__("datetime").date.today().isoformat()).order("reported_date",desc=True).execute().data or [])
        for e in ev: earnings.setdefault(e["company_id"],e)
    result=[{"ticker":r["ticker"],"company":r["company"],"sector":r.get("sector"),"signal":"setup","score":r.get("research_priority_score"),"coverage":r.get("research_priority_coverage"),"catalyst":r.get("research_priority_reason"),"fundamentals":r.get("fundamentals_score"),"valuation":r.get("valuation_score"),"earnings":r.get("earnings_score"),"pe":r.get("pe"),"price_to_fcf":r.get("price_to_fcf"),"as_of_date":r.get("as_of_date"),"opportunity_score":r.get("opportunity_score"),"setup_probability_up":r.get("setup_probability_up"),"setup_median_return_5d":r.get("setup_median_return_5d"),"setup_sample_size":r.get("setup_sample_size"),"upside_to_60d_high":r.get("upside_to_60d_high"),"setup_drawdown_60d":r.get("setup_drawdown_60d"),"opportunity_reason":r.get("opportunity_reason"),"current_price":r.get("current_price"),"price_date":r.get("price_date"),"price_source":r.get("price_source"),"earnings_catalyst":earnings.get(r.get("company_id"))} for r in rows]
    def catalyst_strength(x):
        e=x.get("earnings_catalyst") or {}; vals=[float(v) for v in (e.get("surprise_percent"),e.get("revenue_surprise_percent")) if v is not None]
        return 0 if not vals else max(-8,min(8,sum(max(-20,min(20,v)) for v in vals)/5))
    for x in result:
        base=x.get("opportunity_score"); x["catalyst_adjustment"]=round(catalyst_strength(x),2); x["research_rank_score"]=round(float(base)+x["catalyst_adjustment"],2) if base is not None else None
    result.sort(key=lambda x:x.get("research_rank_score") if x.get("research_rank_score") is not None else -999,reverse=True)
    return result

@router.get("/data-audit")
def data_audit():
    db=get_supabase(); d=db.rpc("research_data_audit").execute().data or {}; total=d.get("universe",0)
    def item(key,label,status):
        count=d.get(key,0); return {"key":key,"label":label,"companies":count,"total":total,"coverage_pct":round(100*count/total,1) if total else 0,"status":status}
    return {"universe":total,"layers":[item("prices","Daily prices","strong"),item("features","Price features","strong"),item("setups","Current setup metrics","strong"),item("fundamentals","Fundamentals","partial"),item("valuation","Valuation","partial"),item("estimates","Analyst estimates","partial"),item("earnings","Historical earnings events","partial")],"missing_price_tickers":d.get("missing_price_tickers",[]),"notes":["Price/setup data is the strongest current layer.","Fundamentals, valuation, estimates and earnings-event coverage are currently pilot-scale."]}

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
    return {"company":c,"snapshots":snapshots,"financials":financials,"analyst_assessment":assessment}

@router.get("/framework")
def framework(): return {"dimensions":["fundamentals","valuation","earnings/revisions","momentum","news/sentiment","catalysts"],"purpose":"Prioritize companies for research; not personalized buy/sell instructions."}

@router.get("/signals")
def signals(limit:int=100):
    db=get_supabase(); rows=(db.table("research_predictions").select("*,companies(ticker,name,sector)").order("signal_date",desc=True).order("rank").limit(min(max(limit,1),500)).execute().data or [])
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
    db=get_supabase(); rows=(db.table("research_predictions").select("horizon_days,actual_return,benchmark_return,excess_return,correct_direction,evaluated_at").execute().data or []); rows=[x for x in rows if x.get("evaluated_at")]
    import statistics
    def stats(xs):
        n=len(xs)
        if not n:return {"evaluated":0,"win_rate":None,"avg_return":None,"median_return":None,"avg_excess_return":None,"beat_spy_rate":None}
        rets=[float(x["actual_return"]) for x in xs if x.get("actual_return") is not None]; excess=[float(x["excess_return"]) for x in xs if x.get("excess_return") is not None]
        return {"evaluated":n,"win_rate":sum(bool(x.get("correct_direction")) for x in xs)/n,"avg_return":sum(rets)/len(rets) if rets else None,"median_return":statistics.median(rets) if rets else None,"avg_excess_return":sum(excess)/len(excess) if excess else None,"beat_spy_rate":sum(x>0 for x in excess)/len(excess) if excess else None}
    return {"overall":stats(rows),"by_horizon":{str(h):stats([x for x in rows if x.get("horizon_days")==h]) for h in (5,10,20)}}

@router.get("/system-health")
def system_health():
    db=get_supabase()
    runs=(db.table("pipeline_runs").select("*").eq("pipeline","daily_market_research").order("started_at",desc=True).limit(1).execute().data or [])
    source_runs=(db.table("pipeline_runs").select("*").eq("pipeline","research_sources_refresh").order("started_at",desc=True).limit(1).execute().data or [])
    latest=(db.table("price_history").select("price_date").order("price_date",desc=True).limit(1).execute().data or [])
    feature=(db.table("price_features").select("feature_date").order("feature_date",desc=True).limit(1).execute().data or [])
    audit=db.rpc("research_data_audit").execute().data or {}
    run=runs[0] if runs else None
    source_run=source_runs[0] if source_runs else None
    return {
        "status":run.get("status") if run else "not_run",
        "last_run":run,
        "latest_price_date":latest[0]["price_date"] if latest else None,
        "latest_feature_date":feature[0]["feature_date"] if feature else None,
        "research_sources_run":source_run,
        "coverage":{
            "universe":audit.get("universe",0),
            "fundamentals":audit.get("fundamentals",0),
            "earnings":audit.get("earnings",0),
            "valuation":audit.get("valuation",0),
            "estimates":audit.get("estimates",0),
        },
    }
