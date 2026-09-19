import sys
from datetime import date
from pathlib import Path
from dotenv import load_dotenv
API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.research.priority import calculate

db=get_supabase(); today=str(date.today())
companies=db.table("companies").select("id,ticker").execute().data or []
queue=[]
for c in companies:
    snaps=(db.table("research_snapshots").select("*").eq("company_id",c["id"])
           .order("as_of_date",desc=True).limit(2).execute().data or [])
    if not snaps: continue
    current=snaps[0]; previous=snaps[1] if len(snaps)>1 else None
    result=calculate(current,previous)
    db.table("research_snapshots").update({
      "research_priority_score":result.score,
      "research_priority_coverage":result.coverage,
      "research_priority_reason":result.reason
    }).eq("id",current["id"]).execute()
    queue.append((result.score if result.score is not None else -1,c["ticker"],result))
for _,ticker,r in sorted(queue,reverse=True):
    print(ticker,"priority=",r.score,f"coverage={r.coverage}%","|",r.reason)
