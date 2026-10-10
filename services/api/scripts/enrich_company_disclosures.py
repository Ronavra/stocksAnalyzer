import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.client import get_supabase
from app.providers.sec import SECProvider
from app.providers.sec_documents import release_documents
from app.research.guidance import extract_guidance, PARSER_VERSION


async def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--limit",type=int,default=300); args=parser.parse_args()
    db=get_supabase(); provider=SECProvider(); started=datetime.now(timezone.utc).isoformat()
    run=db.table("pipeline_runs").insert({"pipeline":"sec_guidance_refresh","status":"running","started_at":started}).execute().data[0]
    rows=db.table("company_disclosures").select("*").in_("form",["8-K","8-K/A","6-K","6-K/A"]).or_(f"enriched_at.is.null,enrichment_parser.neq.{PARSER_VERSION},enrichment_parser.is.null,enrichment_status.eq.error").gte("filing_date",(datetime.now(timezone.utc)-timedelta(days=90)).date().isoformat()).order("filing_date",desc=True).limit(min(args.limit,500)).execute().data or []
    count=processed=0; errors=[]
    for event in rows:
        if event["form"].startswith("8-K") and not set(event.get("items") or [])&{"2.02","7.01","8.01"}:
            db.table("company_disclosures").update({"enriched_at":started,"enrichment_status":"not_earnings_or_outlook","enrichment_parser":PARSER_VERSION}).eq("id",event["id"]).execute()
            continue
        try:
            payload=[]
            for url,html in await release_documents(provider,event):
                # Availability is when this extraction was first observed,
                # rather than when only the filing metadata was collected.
                extracted_at=datetime.now(timezone.utc).isoformat()
                payload.extend(extract_guidance(html,event["company_id"],{**event,"source_url":url,"observed_at":extracted_at}))
                await asyncio.sleep(.2)
            if payload:
                db.table("corporate_guidance_events").upsert(payload,on_conflict="company_id,event_date,fiscal_year,fiscal_period,source,source_record_id",ignore_duplicates=True,returning="minimal").execute()
            db.table("company_disclosures").update({"enriched_at":datetime.now(timezone.utc).isoformat(),"enrichment_status":"guidance_extracted" if payload else "no_explicit_annual_range","enrichment_parser":PARSER_VERSION}).eq("id",event["id"]).execute()
            count+=len(payload); processed+=1
        except Exception as exc:
            errors.append({"accession_number":event["accession_number"],"error":str(exc)[:250]})
            db.table("company_disclosures").update({"enrichment_status":"error"}).eq("id",event["id"]).execute()
    report={"attempted":len(rows),"processed":processed,"guidance_ranges":count,"errors":errors,"bounded_batch":True,"parser":PARSER_VERSION}
    db.table("pipeline_runs").update({"status":"error" if errors else "success","finished_at":datetime.now(timezone.utc).isoformat(),"metadata":report}).eq("id",run["id"]).execute()
    print(json.dumps(report))
    if errors:
        raise RuntimeError("Some SEC release requests failed; successful evidence was retained and failed rows remain retryable")


if __name__=="__main__":
    asyncio.run(main())
