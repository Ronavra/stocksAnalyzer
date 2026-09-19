import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.research.fundamentals import derive,score,scoring_profile

db=get_supabase()
companies=db.table("companies").select("id,ticker,sector,industry").execute().data or []
for company in companies:
    profile=scoring_profile(company)
    rows=(db.table("financial_metrics").select("*").eq("company_id",company["id"])
          .eq("period_type","annual").order("period_end",desc=True).limit(2).execute().data or [])
    if not rows: continue
    signals=derive(rows[0],rows[1] if len(rows)>1 else None)
    fundamental_score,coverage=score(signals,profile)
    db.table("companies").update({"scoring_profile":profile}).eq("id",company["id"]).execute()
    payload={"company_id":company["id"],"as_of_date":str(date.today()),
      "fundamentals_score":fundamental_score,"fundamentals_coverage":coverage,"scoring_profile":profile,
      "what_changed":f"Revenue growth: {signals.revenue_growth:.1%}" if signals.revenue_growth is not None else "Revenue growth unavailable",
      "why_investors_care":("Bank-specific fundamentals require NIM, CET1, ROTCE and credit-quality inputs; generic score withheld."
        if profile=="bank" else "Fundamentals reflect growth, margins, cash generation and balance-sheet pressure.")}
    db.table("research_snapshots").upsert(payload,on_conflict="company_id,as_of_date").execute()
    print(company["ticker"],profile,fundamental_score,f"coverage={coverage}%")
