"""Observe S&P 500 membership changes without rewriting past snapshots.

Dates in index_memberships are first/last observation dates from this source,
not the official effective dates of earlier index announcements.
"""

import csv
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from app.db.client import get_supabase

SOURCE = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"


def normalize_ticker(ticker):
    return str(ticker or "").strip().upper().replace(".", "-")


def parse_constituents(csv_text, current_tickers=()):
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames or not {"Symbol", "Security"}.issubset(reader.fieldnames):
        raise ValueError("Constituent source is missing required columns")
    companies = {}
    for row in reader:
        ticker = normalize_ticker(row.get("Symbol"))
        if not ticker or ticker in companies:
            raise ValueError(f"Missing or duplicate constituent ticker: {ticker!r}")
        companies[ticker] = {"ticker": ticker, "name": row.get("Security") or ticker,
                             "sector": row.get("GICS Sector"),
                             "industry": row.get("GICS Sub-Industry"),
                             "is_sp500": True, "active": True}
    if not 490 <= len(companies) <= 550:
        raise ValueError(f"Unexpected constituent count: {len(companies)}")
    current = set(current_tickers)
    if current and (len(current - companies.keys()) > 10 or len(companies.keys() - current) > 10):
        raise ValueError("Too many constituent changes for one sync; review source before changing membership")
    return companies


def sync(db, csv_text, observed_at):
    today = observed_at.date().isoformat()
    current = db.table("companies").select("id,ticker").eq("is_sp500", True).execute().data or []
    constituents = parse_constituents(csv_text, [c["ticker"] for c in current])
    open_rows = (db.table("index_memberships")
                 .select("id,company_id,effective_from")
                 .eq("index_code", "SP500").is_("effective_to", "null").execute().data or [])
    open_by_company = {r["company_id"]: r for r in open_rows}
    captured_at = observed_at.isoformat()
    active_ids = set()
    added = 0
    for payload in constituents.values():
        saved = db.table("companies").upsert(payload, on_conflict="ticker").execute().data or []
        if not saved:
            raise RuntimeError(f"Company upsert returned no id for {payload['ticker']}")
        cid = saved[0]["id"]
        active_ids.add(cid)
        if cid not in open_by_company:
            db.table("index_memberships").upsert({
                "company_id": cid, "index_code": "SP500", "effective_from": today,
                "effective_to": None, "source": "datasets/s-and-p-500-companies",
                "source_url": SOURCE, "captured_at": captured_at,
            }, on_conflict="company_id,index_code,effective_from").execute()
            added += 1

    removed = 0
    for cid, membership in open_by_company.items():
        if cid not in active_ids:
            # Half-open interval: effective_to is the first observed day out.
            db.table("index_memberships").update({"effective_to": today}).eq("id", membership["id"]).execute()
            removed += 1
    for company in current:
        if company["id"] not in active_ids:
            db.table("companies").update({"is_sp500": False}).eq("id", company["id"]).execute()
    print(f"S&P 500 observed {today}: active={len(active_ids)} added={added} removed={removed}")
    return {"active": len(active_ids), "added": added, "removed": removed}


def main():
    response = httpx.get(SOURCE, timeout=30, follow_redirects=True)
    response.raise_for_status()
    sync(get_supabase(), response.text, datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
