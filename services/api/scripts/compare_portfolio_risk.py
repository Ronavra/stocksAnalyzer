"""Evaluate frozen sector/volatility snapshots; no new stock-selection policies."""
import json
import sys
from datetime import datetime,timezone
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.research.financial_ranking import SIGNAL_VERSION
from app.research.prospective_metrics import paged
from app.research.portfolio_comparison import simulate,load_portfolio_comparison,COST_SCENARIOS
from app.research.portfolio_risk import weights_for


def compare(db):
    baseline=load_portfolio_comparison(db)
    cohorts=paged(db.table("recommendation_cohorts").select("*").eq("model_version",SIGNAL_VERSION).order("signal_date"))
    predictions=paged(db.table("research_predictions").select("company_id,signal_date,model_version,horizon_days,model_diagnostics").eq("model_version",SIGNAL_VERSION).order("id"))
    spy=db.table("companies").select("id").eq("ticker","SPY").single().execute().data["id"]
    ids=sorted({r["company_id"] for r in predictions}|{spy})
    first=min((r["signal_date"] for r in cohorts),default=datetime.now(timezone.utc).date().isoformat())
    prices=paged(db.table("price_history").select("company_id,price_date,close,source").in_("company_id",ids).gte("price_date",first).order("price_date").order("company_id").order("source"))
    # Replay on the same full session calendar used by the production baseline.
    from app.market_calendar import is_trading_day
    from datetime import date,timedelta
    last=baseline.get("latest_market_date") or first;day=date.fromisoformat(first);calendar=[]
    while day<=date.fromisoformat(last):
        if is_trading_day(day): calendar.append(day.isoformat())
        day+=timedelta(days=1)
    experiments={}
    for method in ("equal_sector_cap","inverse_volatility_sector_cap"):
        allocations={};missing=[]
        for c in cohorts:
            rows=[p for p in predictions if p["signal_date"]==c["signal_date"] and p["horizon_days"]==5]
            weights,error=weights_for(rows,method,published_at=c.get("published_at"))
            if error: missing.append({"signal_date":c["signal_date"],"reason":error})
            else: allocations[(c["signal_date"],c["model_version"])]=weights
        if missing or not cohorts:
            experiments[method]={"status":"insufficient_frozen_risk_history","missing":missing};continue
        results={}
        for h in (5,10,20):
            results[str(h)]={}
            for name,cost in COST_SCENARIOS.items():
                replay=simulate(cohorts,predictions,prices,calendar,spy,h,cost,allocation_weights=allocations)
                results[str(h)][name]={k:v for k,v in replay.items() if k!="curve"}
        experiments[method]={"status":"observed_replay","results":results}
    return {"active_version":SIGNAL_VERSION,"experiments":experiments,"published_groups":len(cohorts),
            "baseline_price_return":{h:{s:r["summary"] for s,r in b["price_return"].items()} for h,b in baseline.get("by_policy",{}).get(SIGNAL_VERSION,{}).items()},
            "validated":False,"production_changed":False,"sector_cap":.4,"unallocated_capital":"cash_zero_yield",
            "limitations":["Frozen groups are too few to establish an advantage.","Sector and volatility must be captured at publication; today's classifications never fill old gaps.","These experiments use price returns on both sides; dividend-adjusted production evaluation remains separate."]}


def main():
    db=get_supabase();started=datetime.now(timezone.utc).isoformat()
    try:
        report=compare(db)
        db.table("pipeline_runs").insert({"pipeline":"portfolio_risk_research","status":"success","started_at":started,
            "finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report}).execute()
        (API_DIR/"portfolio_risk_research.json").write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps(report),flush=True)
    except Exception as exc:
        db.table("pipeline_runs").insert({"pipeline":"portfolio_risk_research","status":"error","started_at":started,
            "finished_at":datetime.now(timezone.utc).isoformat(),"error_message":str(exc)[:500]}).execute()
        raise


if __name__=="__main__":main()
