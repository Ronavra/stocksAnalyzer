"""Inspect original filing identities and capital concepts without guessing values."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import httpx
from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR)); load_dotenv(API_DIR / ".env")
from app.db.client import get_supabase
from app.providers.sec import SECProvider, latest_financial_report


async def main():
    db = get_supabase(); provider = SECProvider()
    run = db.table("pipeline_runs").insert({"pipeline": "financial_gap_diagnostics", "status": "running", "started_at": datetime.now(timezone.utc).isoformat()}).execute().data[0]
    companies = db.table("companies").select("id,ticker,cik,scoring_profile,industry").eq("active", True).eq("is_sp500", True).execute().data or []
    selected = [c for c in companies if c["ticker"] in {"FERG", "HON", "HONA", "SKYD", "VYLR", "XOM"} or c.get("scoring_profile") == "bank" or c.get('industry') in ('Diversified Banks','Regional Banks')]
    results = []
    try:
        async with httpx.AsyncClient(timeout=60, headers={"User-Agent": provider.user_agent}) as client:
            for c in selected:
                row = {"ticker": c["ticker"], "cik": c["cik"]}
                try:
                    submissions = await provider.submissions(c["cik"])
                    report = latest_financial_report(submissions)
                    row["report"] = report
                    if not report:
                        row["status"] = "no_financial_report"; results.append(row); continue
                    acc = report["accession_number"]
                    directory = f"https://www.sec.gov/Archives/edgar/data/{int(c['cik'])}/{acc.replace('-', '')}/"
                    response = await client.get(directory + "index.json"); response.raise_for_status()
                    names = [x.get("name", "") for x in response.json().get("directory", {}).get("item", [])]
                    instances = [n for n in names if re.fullmatch(r"[\w.-]+_htm.xml", n)]
                    row["instances"] = instances
                    if len(instances) != 1:
                        row["status"] = "ambiguous_instance"; results.append(row); continue
                    response = await client.get(directory + instances[0]); response.raise_for_status()
                    root = ET.fromstring(response.content)
                    ns = {"x": "http://www.xbrl.org/2003/instance"}
                    contexts = {x.attrib["id"]: x for x in root.findall("x:context", ns)}
                    row["entity_identifiers"] = dict(Counter((x.findtext("x:entity/x:identifier", namespaces=ns) or "") for x in contexts.values()))
                    facts = []
                    for el in root:
                        tag = el.tag.split("}")[-1]
                        if not re.search(r"CommonEquityTier|Tier[1O]|CapitalRatio|RiskBasedCapital|EntityCentralIndexKey|EntityRegistrantName", tag, re.I): continue
                        ctx = contexts.get(el.attrib.get("contextRef"))
                        end = ctx.findtext("x:period/x:instant", namespaces=ns) if ctx is not None else None
                        facts.append({"tag": tag, "value": el.text, "unit": el.attrib.get("unitRef"), "end": end,
                                      "dimensions": [{"axis": x.attrib.get("dimension"), "member": x.text} for x in ctx.iter() if x.tag.endswith("}explicitMember")] if ctx is not None else []})
                    row["capital_and_identity_facts"] = facts[:150]
                    if c['ticker'] in {'FERG','HON','HONA','SKYD','XOM'}:
                        from app.providers.sec import instance_company_facts, facts_by_period, quarter_facts_by_period
                        from scripts.ingest_sec_fundamentals import build_ttm_rows
                        try:
                            parsed=instance_company_facts(response.content,c['cik'],report)
                            annual=facts_by_period(parsed);quarters=quarter_facts_by_period(parsed)
                            row['annual_periods']=annual[-4:];row['quarter_periods']=quarters[-8:];row['ttm_periods']=build_ttm_rows(annual,quarters)[-4:]
                            income=[]
                            for el in root:
                                tag=el.tag.split('}')[-1]
                                ctx=contexts.get(el.attrib.get('contextRef'))
                                if ctx is not None and tag in ('Revenues','RevenueFromContractWithCustomerExcludingAssessedTax','NetIncomeLoss','OperatingIncomeLoss','EarningsPerShareDiluted'):
                                    income.append({'tag':tag,'value':el.text,'start':ctx.findtext('x:period/x:startDate',namespaces=ns),'end':ctx.findtext('x:period/x:endDate',namespaces=ns),
                                                   'dimensions':[{'axis':x.attrib.get('dimension'),'member':x.text} for x in ctx.iter() if x.tag.endswith('}explicitMember')]})
                            row['income_facts']=income[:80]
                        except Exception as exc:row['parse_error']=type(exc).__name__
                    row["status"] = "inspected"
                except Exception as exc:
                    row.update(status="error", error_type=type(exc).__name__)
                results.append(row); await asyncio.sleep(.2)
        report = {"companies": results, "diagnostic_only": True}
        db.table("pipeline_runs").update({"status": "success", "finished_at": datetime.now(timezone.utc).isoformat(), "metadata": report}).eq("id", run["id"]).execute()
        print(json.dumps(report), flush=True)
    except Exception as exc:
        db.table("pipeline_runs").update({"status": "error", "finished_at": datetime.now(timezone.utc).isoformat(), "error_message": type(exc).__name__}).eq("id", run["id"]).execute()
        raise


if __name__ == "__main__":
    asyncio.run(main())
