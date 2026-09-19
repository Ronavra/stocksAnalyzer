import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")

from app.db.client import get_supabase
from app.research.fundamentals import derive,score

db=get_supabase()
companies=db.table("companies").select("id,ticker").execute().data or []
for company in companies:
    rows=(db.table("financial_metrics").select("*")
          .eq("company_id",company["id"]).eq("period_type","annual")
          .order("period_end",desc=True).limit(2).execute().data or [])
    if not rows: continue
    signals=derive(rows[0], rows[1] if len(rows)>1 else None)
    fundamental_score=score(signals)
    payload={
      "company_id":company["id"],"as_of_date":str(date.today()),
      "fundamentals_score":fundamental_score,
      "what_changed":f"Revenue growth: {signals.revenue_growth:.1%}" if signals.revenue_growth is not None else "Revenue growth unavailable",
      "why_investors_care":"Fundamental score currently reflects growth, operating margin, margin change, free-cash-flow margin and balance-sheet pressure.",
    }
    db.table("research_snapshots").upsert(payload,on_conflict="company_id,as_of_date").execute()
    print(company["ticker"], fundamental_score)
