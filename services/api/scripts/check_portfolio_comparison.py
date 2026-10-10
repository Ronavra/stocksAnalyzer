"""Record an auditable comparison snapshot without publishing recommendations."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.research.portfolio_comparison import load_portfolio_comparison


def snapshot(report):
    return {**{k:v for k,v in report.items() if k!="by_policy"},
            "by_policy":{version:{horizon:{basis:{scenario:{k:v for k,v in result.items() if k!="curve"}
                        for scenario,result in scenarios.items()} for basis,scenarios in bases.items()}
                        for horizon,bases in horizons.items()} for version,horizons in report["by_policy"].items()}}


def main():
    db=get_supabase()
    created=db.table("pipeline_runs").insert({"pipeline":"portfolio_comparison","status":"running",
                    "started_at":datetime.now(timezone.utc).isoformat()}).execute().data or []
    run_id=created[0]["id"] if created else None
    try:
        report=snapshot(load_portfolio_comparison(db))
        blocked=[{"policy":version,"horizon":h,"basis":basis,"issues":results["base"]["issues"]}
                 for version,horizons in report["by_policy"].items() for h,bases in horizons.items()
                 for basis,results in bases.items() if results["base"]["status"]=="blocked"]
        error="Portfolio comparison incomplete" if blocked or not report.get("market_current") else None
        if run_id:
            db.table("pipeline_runs").update({"status":"error" if error else "success",
                  "finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report,
                  "error_message":error}).eq("id",run_id).execute()
        print(json.dumps({"active_version":report.get("active_version"),"latest_market_date":report.get("latest_market_date"),
              "blocked":blocked,"active_portfolios":report["by_policy"].get(report.get("active_version"),{})}),flush=True)
        if error:
            raise RuntimeError(error)
    except Exception as exc:
        if run_id:
            db.table("pipeline_runs").update({"status":"error","finished_at":datetime.now(timezone.utc).isoformat(),
                    "error_message":str(exc)[:500]}).eq("id",run_id).execute()
        raise


if __name__=="__main__":
    main()
