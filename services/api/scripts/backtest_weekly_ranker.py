"""Read-only replay of weekly Top 5 setup ranking versus SPY."""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from app.db.client import get_supabase
from app.research.weekly_backtest import replay, summarize


def paged(query, page_size=1000):
    rows = []
    start = 0
    while True:
        page = query.range(start, start + page_size - 1).execute().data or []
        rows.extend(page)
        if len(page) < page_size:
            return rows
        start += page_size


def run(db, start_date):
    companies = db.table("companies").select("id,ticker").eq("is_sp500", True).execute().data or []
    spy = db.table("companies").select("id").eq("ticker", "SPY").limit(1).execute().data or []
    if not spy:
        raise RuntimeError("SPY benchmark is missing")
    spy_id = spy[0]["id"]
    cutoff = (date.fromisoformat(start_date) - timedelta(days=365 * 4)).isoformat()
    columns = "feature_date,close,drawdown_60d,distance_to_support_60d,rebound_potential_60d,forward_return_5d,forward_return_10d,forward_return_20d"
    series = {}
    for index, company in enumerate([*companies, {"id": spy_id, "ticker": "SPY"}], 1):
        cid = company["id"]
        if cid in series:
            continue
        series[cid] = paged(db.table("price_features").select(columns)
                            .eq("company_id", cid).gte("feature_date", cutoff)
                            .order("feature_date"))
        if index % 50 == 0:
            print(f"Loaded price histories for {index}/{len(companies) + 1} tickers", flush=True)

    events = paged(db.table("earnings_events")
                   .select("company_id,reported_date,surprise_percent,revenue_surprise_percent")
                   .eq("source", "massive_benzinga")
                   .gte("reported_date", (date.fromisoformat(start_date) - timedelta(days=31)).isoformat())
                   .order("reported_date"))
    earnings = {}
    for event in events:
        earnings.setdefault(event["company_id"], []).append(event)
    weeks = replay(series, earnings, spy_id, start_date)
    tickers = {c["id"]: c["ticker"] for c in companies}
    cohorts = [{"date": week["date"], "eligible": len(week["eligible"]),
                "setup_only": [tickers[p["company_id"]] for p in week["setup_only"]],
                "recent_earnings": [tickers[p["company_id"]] for p in week["recent_earnings"]]}
               for week in weeks]
    return {
        "start_date": start_date,
        "last_available_price_date": series[spy_id][-1]["feature_date"],
        "current_constituents": len(companies),
        "method": "Friday or last trading session each week; 750-row setup history; purge five trading rows; Top 5 at close; equal weights; 5/10/20 trading-day close-to-close returns",
        "limitations": [
            "Historical universe uses today's S&P 500 constituents; delisted and removed companies are absent (survivorship bias).",
            "Historical earnings surprises were backfilled and can include later provider revisions; treat earnings comparison as exploratory.",
            "Weekly cohorts overlap at 10- and 20-day horizons; win rates are descriptive, not independent significance tests.",
            "Scores and thresholds replicate the current heuristic; no parameter selection or optimization was performed on these outcomes.",
            "The 30-day catalyst window is a fixed production rule and has not been optimized or proven to improve returns.",
        ],
        **summarize(weeks),
        "cohorts": cohorts,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--output", default="weekly_backtest.json")
    args = parser.parse_args()
    result = run(get_supabase(), args.start_date)
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cohorts"}, indent=2), flush=True)


if __name__ == "__main__":
    main()
