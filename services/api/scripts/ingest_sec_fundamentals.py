import argparse
import asyncio
import sys
import time
import json
from datetime import datetime, timezone, date
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_DIR))
load_dotenv(API_DIR / ".env")

from app.db.client import get_supabase
from app.providers.sec import SECProvider, facts_by_period, quarter_facts_by_period, shares_outstanding_by_period, latest_financial_report, merge_company_facts
from app.research.financial_quality import company_quality, summarize_quality
from app.research.company_disclosures import current_reports

DURATION_FIELDS=("revenue","operating_income","net_income","eps_diluted","free_cash_flow","capex")

def upsert_company_metrics(db, company_id, annual_rows, quarter_rows, ttm_rows, captured_at):
    payloads=[]
    for period_type, rows in (("annual", annual_rows), ("quarter", quarter_rows), ("ttm", ttm_rows)):
        for x in rows:
            payloads.append({
                "company_id": company_id,
                "period_end": x["period_end"],
                "period_type": period_type,
                "revenue": x.get("revenue"),
                "operating_income": x.get("operating_income"),
                "net_income": x.get("net_income"),
                "eps_diluted": x.get("eps_diluted"),
                "free_cash_flow": x.get("free_cash_flow"),
                "capex": x.get("capex"),
                "cash": x.get("cash"),
                "total_debt": x.get("total_debt"),
                "shares_outstanding": x.get("shares_outstanding"),
                "source": "sec",
                "filed_date": x.get("filed_date"),
                "accession_number": x.get("accn"),
                "captured_at": captured_at,
            })
    if payloads:
        # One database request per company instead of one per filing period.
        db.table("financial_metrics").upsert(
            payloads, on_conflict="company_id,period_end,period_type", returning="minimal"
        ).execute()
    return len(payloads)

def validate_full_refresh(total, successful, ttm_companies, ttm_fcf_companies):
    if (not total or successful/total < .90 or ttm_companies/total < .70
        or ttm_fcf_companies/total < .50):
        raise RuntimeError(
            f"SEC coverage below minimum: companies={successful}/{total}, "
            f"TTM companies={ttm_companies}/{total}, "
            f"latest TTM FCF companies={ttm_fcf_companies}/{total}"
        )

def d(v):
    return date.fromisoformat(v) if isinstance(v,str) else v

def build_ttm_rows(annual_rows, quarter_rows):
    # Derive fiscal Q4 from the annual filing minus the three 10-Q quarters,
    # then build rolling four-quarter TTM rows. filed_date is the latest filing
    # needed for the TTM value, which makes point-in-time joins safe.
    annual=sorted(annual_rows,key=lambda x:x["period_end"])
    quarters=[dict(x) for x in quarter_rows]
    prev_end=None
    for a in annual:
        a_end=d(a["period_end"])
        candidates=[
            q for q in quarters
            if d(q["period_end"])<a_end
            and (prev_end is None or d(q["period_end"])>prev_end)
            and (a_end-d(q["period_end"])).days<=330
        ]
        candidates=sorted(candidates,key=lambda x:x["period_end"])[-3:]
        gaps=[(d(right["period_end"])-d(left["period_end"])).days for left,right in zip(candidates,candidates[1:])]
        if (len(candidates)==3 and all(60<=gap<=120 for gap in gaps)
                and 60<=(a_end-d(candidates[-1]["period_end"])).days<=120):
            q4={"period_end":a["period_end"],"filed_date":a.get("filed_date"),"accn":a.get("accn")}
            for field in DURATION_FIELDS:
                av=a.get(field); vals=[q.get(field) for q in candidates]
                q4[field]=float(av)-sum(float(v) for v in vals) if av is not None and all(v is not None for v in vals) else None
            q4["cash"]=a.get("cash")
            q4["total_debt"]=a.get("total_debt")
            q4["shares_outstanding"]=a.get("shares_outstanding")
            existing=next((q for q in quarters if q["period_end"]==q4["period_end"]),None)
            if existing:
                for key,value in q4.items():
                    if existing.get(key) is None:
                        existing[key]=value
                existing["filed_date"]=max(existing.get("filed_date") or "",q4.get("filed_date") or "")
            else:
                quarters.append(q4)
        prev_end=a_end

    quarters=sorted({q["period_end"]:q for q in quarters}.values(),key=lambda x:x["period_end"])
    # A real annual statement already covers twelve months. Missing quarters
    # must not prevent that annual report from being available as TTM.
    out={a["period_end"]:dict(a) for a in annual}
    for i in range(3,len(quarters)):
        window=quarters[i-3:i+1]
        gaps=[(d(right["period_end"])-d(left["period_end"])).days for left,right in zip(window,window[1:])]
        if not all(60<=gap<=120 for gap in gaps):
            continue
        rec={"period_end":window[-1]["period_end"]}
        for field in DURATION_FIELDS:
            vals=[q.get(field) for q in window]
            rec[field]=sum(float(v) for v in vals) if all(v is not None for v in vals) else None
        rec["cash"]=window[-1].get("cash")
        rec["total_debt"]=window[-1].get("total_debt")
        rec["shares_outstanding"]=window[-1].get("shares_outstanding")
        filed=[q.get("filed_date") for q in window if q.get("filed_date")]
        rec["filed_date"]=max(filed) if filed else None
        rec["accn"]=window[-1].get("accn")
        if sum(rec.get(k) is not None for k in ("revenue","operating_income","net_income","eps_diluted"))>=2:
            if rec["period_end"] in out:
                # The reported full year is more authoritative than a sum of
                # rounded quarterly EPS or partly missing derived quarters.
                rec={**rec,**out[rec["period_end"]]}
            out[rec["period_end"]]=rec
    # A missing Q3/Q4 field can still be recovered exactly from a reported
    # full year + current YTD - the same prior-year YTD. Require complete,
    # matching Q1/Q2/Q3 sequences anchored to consecutive fiscal year ends.
    for previous,a in zip(annual,annual[1:]):
        previous_end=d(previous["period_end"]); a_end=d(a["period_end"])
        if not 330<=(a_end-previous_end).days<=400:
            continue
        current=sorted((q for q in quarters if 0<(d(q["period_end"])-a_end).days<=310),key=lambda q:q["period_end"])
        prior=sorted((q for q in quarters if previous_end<d(q["period_end"])<a_end),key=lambda q:q["period_end"])
        for count in range(1,min(len(current),3)+1):
            now=current[:count]; before=prior[:count]
            if len(before)!=count:
                continue
            now_gaps=[(d(q["period_end"])-base).days for base,q in zip([a_end]+[d(q["period_end"]) for q in now[:-1]],now)]
            prior_gaps=[(d(q["period_end"])-base).days for base,q in zip([previous_end]+[d(q["period_end"]) for q in before[:-1]],before)]
            if not all(60<=gap<=120 for gap in now_gaps+prior_gaps):
                continue
            if any(abs((d(n["period_end"])-a_end).days-(d(p["period_end"])-previous_end).days)>14 for n,p in zip(now,before)):
                continue
            end=now[-1]["period_end"]
            rec=out.setdefault(end,{"period_end":end})
            used=False
            for field in DURATION_FIELDS:
                vals=[q.get(field) for q in now+before]
                if rec.get(field) is None and a.get(field) is not None and all(v is not None for v in vals):
                    rec[field]=float(a[field])+sum(float(q[field]) for q in now)-sum(float(q[field]) for q in before)
                    used=True
            for field in ("cash","total_debt","shares_outstanding"):
                if rec.get(field) is None:
                    rec[field]=now[-1].get(field)
            if used:
                rec["filed_date"]=max([rec.get("filed_date") or "",a.get("filed_date") or ""]+[q.get("filed_date") or "" for q in now+before])
                rec["accn"]=now[-1].get("accn")
    out={end:rec for end,rec in out.items() if sum(rec.get(k) is not None for k in ("revenue","operating_income","net_income","eps_diluted"))>=2}
    return [out[key] for key in sorted(out)]



async def main():
    p = argparse.ArgumentParser(description="Ingest annual fundamentals from official SEC Company Facts")
    p.add_argument("--tickers", nargs="*")
    p.add_argument("--all", action="store_true")
    p.add_argument("--batch-size", type=int, default=10)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--delay", type=float, default=.15)
    p.add_argument("--years", type=int, default=10)
    p.add_argument("--quarters", type=int, default=16)
    a = p.parse_args()

    db = get_supabase()
    provider = SECProvider()
    companies = (
        db.table("companies")
        .select("id,ticker,cik")
        .eq("is_sp500", True)
        .order("ticker")
        .execute()
        .data
        or []
    )

    if a.tickers:
        wanted = {x.upper() for x in a.tickers}
        companies = [x for x in companies if x["ticker"] in wanted]
    elif not a.all:
        companies = companies[a.offset : a.offset + a.batch_size]

    ticker_map = await provider.ticker_map()
    ok = failed = saved = ttm_companies = ttm_fcf_companies = 0
    started_at=datetime.now(timezone.utc).isoformat()
    quality=[]
    disclosure_count=0

    for i, company in enumerate(companies):
        if i and a.delay:
            time.sleep(a.delay)

        if not company.get("cik"):
            company["cik"] = ticker_map.get(company["ticker"])
            if company.get("cik"):
                db.table("companies").update({"cik": company["cik"]}).eq("id", company["id"]).execute()

        if not company.get("cik"):
            print(company["ticker"], "missing SEC CIK mapping")
            failed += 1
            quality.append({"ticker":company["ticker"],"company_id":company["id"],"status":"missing_cik"})
            continue

        try:
            result = await provider.company_facts(company["cik"])
            submission_error=None
            disclosure_error=None
            try:
                submissions=await provider.submissions(company["cik"])
                latest_report=latest_financial_report(submissions)
            except Exception as exc:
                latest_report=None
                submission_error=str(exc)
            if not submission_error:
                try:
                    observed_at=datetime.now(timezone.utc).isoformat()
                    disclosures=current_reports(company,submissions,observed_at)
                    if disclosures:
                        db.table("company_disclosures").upsert(disclosures,on_conflict="company_id,accession_number",returning="minimal",ignore_duplicates=True).execute()
                        disclosure_count+=len(disclosures)
                except Exception as exc:
                    disclosure_error=str(exc)[:500]
                    print(company["ticker"],"Disclosure collection failed:",type(exc).__name__)
            annual_rows = facts_by_period(result.value, a.years)
            quarter_rows = quarter_facts_by_period(result.value, a.quarters)
            source_data=result.value
            fallback_error=None; fallback_used=False
            parsed=max([r["period_end"] for r in annual_rows+quarter_rows],default="")
            if latest_report and parsed<latest_report["period_end"]:
                try:
                    source_data=merge_company_facts(source_data,await provider.filing_facts(company["cik"],latest_report))
                    annual_rows=facts_by_period(source_data,a.years)
                    quarter_rows=quarter_facts_by_period(source_data,a.quarters)
                    fallback_used=True
                except Exception as exc:
                    fallback_error=str(exc)[:500]
                    print(company["ticker"],"SEC filing fallback unavailable:",fallback_error)
            shares_map = shares_outstanding_by_period(source_data)

            def attach_shares(rows):
                share_dates=sorted(shares_map)
                for row in rows:
                    end=d(row["period_end"])
                    filed=d(row["filed_date"]) if row.get("filed_date") else None
                    candidates=[]
                    for sd in share_dates:
                        meta=shares_map[sd]
                        share_end=d(sd)
                        share_filed=d(meta["filed"]) if meta.get("filed") else None
                        if abs((share_end-end).days)>180:
                            continue
                        if filed and share_filed and share_filed>filed:
                            continue
                        candidates.append(sd)
                    if candidates:
                        chosen=max(candidates,key=lambda sd:(shares_map[sd].get("filed") or "",sd))
                        row["shares_outstanding"]=shares_map[chosen].get("shares_outstanding")
                return rows

            annual_rows=attach_shares(annual_rows)
            quarter_rows=attach_shares(quarter_rows)
            ttm_rows = build_ttm_rows(annual_rows, quarter_rows)
            captured_at=datetime.now(timezone.utc).isoformat()
            n=upsert_company_metrics(db,company["id"],annual_rows,quarter_rows,ttm_rows,captured_at)
            item=company_quality(company,annual_rows,quarter_rows,ttm_rows,latest_report)
            item["filing_fallback_used"]=fallback_used
            item["companyfacts_latest_period"]=parsed or None
            if fallback_error:
                item["filing_fallback_error"]=fallback_error
            if disclosure_error:
                item["disclosure_error"]=disclosure_error
            if submission_error:
                item["status"]="filing_check_failed"
                item["error"]=submission_error
            quality.append(item)
            ok += 1
            ttm_companies += bool(ttm_rows)
            ttm_fcf_companies += bool(ttm_rows and ttm_rows[-1].get("free_cash_flow") is not None)
            saved += n
            print(company["ticker"], "SEC annual=", len(annual_rows), "quarter=", len(quarter_rows), "ttm=", len(ttm_rows))
        except Exception as exc:
            failed += 1
            print(company["ticker"], "SEC unavailable:", exc)
            quality.append({"ticker":company["ticker"],"company_id":company["id"],"status":"refresh_failed","error":str(exc)[:500]})

    print(f"Done companies_ok={ok} failed={failed} TTM companies={ttm_companies} latest_TTM_FCF={ttm_fcf_companies} rows_saved={saved}")
    report={"started_at":started_at,"finished_at":datetime.now(timezone.utc).isoformat(),
            "scope":"full_universe" if a.all else "selected_companies",
            "summary":summarize_quality(quality),"companies":quality,"disclosure_events_processed":disclosure_count}
    (API_DIR/"sec_fundamentals_audit.json").write_text(json.dumps(report,indent=2)+"\n")
    print("SEC financial quality:",json.dumps(report["summary"]))
    if a.all:
        validate_full_refresh(len(companies),ok,ttm_companies,ttm_fcf_companies)


if __name__ == "__main__":
    asyncio.run(main())
