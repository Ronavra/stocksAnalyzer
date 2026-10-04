"""Free Yahoo fallback for internal holes omitted by the primary price provider."""
import json
import sys
from datetime import date, timedelta
from pathlib import Path
API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
from app.research.price_gap_fallback import corroborated_gap_bars

def load_rows(db, company_id, start, end):
    rows = []
    for offset in range(0, 100000, 1000):
        page = (db.table("price_history").select("company_id,price_date,open,high,low,close,volume,source")
                .eq("company_id", company_id).gte("price_date", str(start)).lte("price_date", str(end))
                .order("price_date").order("source").range(offset, offset+999).execute().data or [])
        rows.extend(page)
        if len(page) < 1000:
            break
    return rows

def repair_gaps(db, tickers, since, until):
    gaps = db.rpc("price_history_gaps", {"p_since":str(since), "p_until":str(until)}).execute().data or []
    wanted = set(tickers)
    gaps = [g for g in gaps if g["ticker"] in wanted]
    if not gaps:
        return []
    import yfinance as yf
    spy = db.table("companies").select("id").eq("ticker", "SPY").single().execute().data
    repaired = []
    for gap in gaps:
        try:
            if gap["missing_sessions"] > 40:
                raise ValueError("Fallback limited to 40 internal missing sessions per company")
            start = date.fromisoformat(gap["first_missing"]) - timedelta(days=7)
            end = min(until, date.fromisoformat(gap["last_missing"]) + timedelta(days=7))
            existing = load_rows(db, gap["company_id"], start, end)
            calendar = {r["price_date"] for r in load_rows(db, spy["id"], start, end)}
            # Yahoo Close is split adjusted; auto_adjust also adjusts dividends.
            frame = yf.Ticker(gap["ticker"].replace(".", "-")).history(
                start=str(start), end=str(end+timedelta(days=1)), interval="1d",
                auto_adjust=False, back_adjust=False, actions=False, repair=False, timeout=20)
            if frame.empty:
                raise ValueError("Fallback returned no daily bars")
            candidates = []
            for timestamp, row in frame.iterrows():
                candidates.append({"price_date":timestamp.date().isoformat(),
                    "open":float(row["Open"]), "high":float(row["High"]),
                    "low":float(row["Low"]), "close":float(row["Close"]),
                    "volume":int(row["Volume"])})
            bars = corroborated_gap_bars(existing, candidates, calendar)
            payload = [{**r, "company_id":gap["company_id"], "source":"yahoo_finance"} for r in bars]
            if payload:
                db.table("price_history").upsert(payload,
                    on_conflict="company_id,price_date,source", ignore_duplicates=True).execute()
                repaired.append(gap["ticker"])
            print(json.dumps({"price_gap_fallback":gap["ticker"], "source":"yahoo_finance",
                              "corroborated_dates":[r["price_date"] for r in bars]}), flush=True)
        except Exception as exc:
            # The quality gate retains unresolved holes; never manufacture a price.
            print(json.dumps({"price_gap_fallback":gap["ticker"], "status":"unresolved",
                              "reason":str(exc)[:300]}), flush=True)
    return repaired
