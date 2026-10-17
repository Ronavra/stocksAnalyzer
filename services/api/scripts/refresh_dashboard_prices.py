"""Prioritize the current frozen shortlist and SPY without another universe run."""
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR));load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.market_calendar import latest_completed_session
from app.research.financial_ranking import SIGNAL_VERSION


def main():
    db=get_supabase()
    cohorts=db.table("recommendation_cohorts").select("signal_date,model_version").eq("model_version",SIGNAL_VERSION).order("signal_date",desc=True).limit(1).execute().data or []
    ids=set()
    if cohorts:
        rows=db.table("research_predictions").select("company_id").eq("signal_date",cohorts[0]["signal_date"]).eq("model_version",SIGNAL_VERSION).execute().data or []
        ids={row["company_id"] for row in rows}
    companies=db.table("companies").select("id,ticker").execute().data or []
    tickers=sorted({c["ticker"] for c in companies if c["id"] in ids or c["ticker"]=="SPY"})
    if "SPY" not in tickers or len(tickers)>6:
        raise RuntimeError("Expected SPY and at most five current weekly picks")
    end=latest_completed_session().isoformat()
    # The existing collector checks the latest stored date per symbol before
    # each request. The broad daily run will skip symbols recovered here.
    subprocess.run([sys.executable,str(API_DIR/"scripts/ingest_prices.py"),"--tickers",*tickers,
                    "--repair-since",end,"--daily-credit-budget","12","--delay","8.5"],check=True,cwd=API_DIR)
    for company in companies:
        if company["ticker"] not in tickers:continue
        prices=db.table("price_history").select("close").eq("company_id",company["id"]).eq("price_date",end).execute().data or []
        if not any(row.get("close") and float(row["close"])>0 for row in prices):
            raise RuntimeError(f"Dashboard price missing for {company['ticker']} on {end}")
    print(f"Current portfolio and SPY prices verified through {end}: {', '.join(tickers)}",flush=True)


if __name__=="__main__":main()
