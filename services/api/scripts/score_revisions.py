import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.research.earnings import derive,score

db=get_supabase()
companies=db.table("companies").select("id,ticker").execute().data or []
today=str(date.today())
for c in companies:
    rows=(db.table("analyst_estimates").select("*").eq("company_id",c["id"])
          .gte("period_end",today).order("period_end").order("estimate_date",desc=True).execute().data or [])
    if not rows: continue
    target=rows[0]["period_end"]
    snapshots=[r for r in rows if r["period_end"]==target]
    latest=snapshots[0]; previous=snapshots[1] if len(snapshots)>1 else None
    signals=derive(latest,previous)
    value,coverage=score(signals)
    db.table("research_snapshots").upsert({
      "company_id":c["id"],"as_of_date":today,"earnings_score":value,"earnings_coverage":coverage
    },on_conflict="company_id,as_of_date").execute()
    print(c["ticker"],target,"revision_score=",value,f"coverage={coverage}%","baseline_pending" if previous is None else "")
