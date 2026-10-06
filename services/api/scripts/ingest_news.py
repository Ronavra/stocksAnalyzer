import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.massive import MassiveProvider
from app.research.news import article_rows


async def main():
    db=get_supabase(); started=datetime.now(timezone.utc).isoformat()
    created=db.table("pipeline_runs").insert({"pipeline":"news_refresh","status":"running","started_at":started}).execute().data or []
    run_id=created[0]["id"] if created else None
    try:
        companies={r["ticker"]:r["id"] for r in db.table("companies").select("id,ticker").eq("is_sp500",True).execute().data or []}
        previous=db.table("pipeline_runs").select("metadata").eq("pipeline","news_refresh").eq("status","success").order("finished_at",desc=True).limit(1).execute().data or []
        mark=(previous[0].get("metadata") or {}).get("watermark") if previous else None
        since=(datetime.fromisoformat(mark)-timedelta(hours=30)).isoformat() if mark else (datetime.now(timezone.utc)-timedelta(days=7)).isoformat()
        articles=await MassiveProvider().news(since,started)
        rows=[r for article in articles for r in article_rows(article,companies,started)]
        for offset in range(0,len(rows),300):
            db.table("news_events").upsert(rows[offset:offset+300],on_conflict="company_id,source,source_record_id",ignore_duplicates=True,returning="minimal").execute()
        report={"articles_received":len(articles),"company_articles":len(rows),"companies":len({r['company_id'] for r in rows}),
                "provider_sentiment_rows":sum(r['sentiment'] is not None for r in rows),"watermark":started,"coverage_is_not_completeness":True}
        db.table("pipeline_runs").update({"status":"success","finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report}).eq("id",run_id).execute()
        print(json.dumps(report))
    except Exception as exc:
        db.table("pipeline_runs").update({"status":"error","finished_at":datetime.now(timezone.utc).isoformat(),"error_message":str(exc)[:1000]}).eq("id",run_id).execute()
        raise


if __name__=="__main__":
    asyncio.run(main())
