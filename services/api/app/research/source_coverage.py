"""Evidence coverage is separate from collection health and predictive value."""
from datetime import datetime, timedelta, timezone
from ..market_calendar import NY, latest_completed_session

FAMILIES = {
    "market": "Price, volume and technical context",
    "financials": "Financial statements and filing freshness",
    "valuation": "Current valuation",
    "earnings": "Reported earnings",
    "upcoming": "Upcoming earnings and consensus",
    "analyst": "Analyst recommendations",
    "estimates": "Forward EPS and revenue estimates",
    "revisions": "Observed estimate revisions",
    "disclosures": "Official company filings",
    "news": "Company news",
    "guidance": "Management guidance",
    "actions": "Dividends and corporate actions",
    "calls": "Earnings calls and presentations",
    "ownership": "Insider trades and institutional ownership",
    "macro": "Rates, inflation and economic calendar",
}


def recent(value, now, hours):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return timedelta(0) <= now - stamp <= timedelta(hours=hours)
    except (AttributeError, ValueError, TypeError):
        return False


def company_coverage(raw, financial_audit=None, checked_at=None, now=None):
    now = now or datetime.now(timezone.utc)
    market_date = latest_completed_session(now.astimezone(NY)).isoformat()
    layers = []

    def add(key, status, detail, observed=None):
        layers.append({"key": key, "label": FAMILIES[key], "status": status,
                       "detail": detail, "observed_at": observed})

    price, features = raw.get("price_date"), raw.get("feature_date")
    add("market", "current" if price == market_date and features == market_date else "stale" if price else "missing",
        f"Price {price or 'unavailable'}; features {features or 'unavailable'}; expected {market_date}. Market and sector price context are derived from these observations.")
    financial = financial_audit or {}
    fresh_audit = recent(checked_at, now, 30)
    fs = "current" if financial.get("status") == "current" and fresh_audit else "stale" if raw.get("financial") else "missing"
    missing = financial.get("missing_fields") or []
    if fs == "current" and missing:
        fs = "partial"
    add("financials", fs, f"Filing audit: {financial.get('status', 'not verified')}. Missing reported fields: {', '.join(missing) or 'none in the audit'}; requirements vary by industry.", checked_at)
    valuation = raw.get("valuation_date")
    add("valuation", "current" if valuation == market_date else "stale" if valuation else "missing", f"Valuation date {valuation or 'unavailable'}.")
    earnings = raw.get("earnings") or {}
    add("earnings", "observed" if earnings.get("reported_date") else "missing", f"Latest reported EPS event {earnings.get('reported_date') or 'unavailable'}.")
    add("upcoming", "observed" if earnings.get("upcoming_eps") and earnings.get("upcoming_revenue") else "partial" if earnings.get("next_date") else "missing",
        f"Next stored report {earnings.get('next_date') or 'unavailable'}; EPS/revenue estimates within 120 days: {earnings.get('upcoming_eps', 0)}/{earnings.get('upcoming_revenue', 0)}. Event dates can change.")
    analyst = raw.get("analyst") or {}
    add("analyst", "current" if analyst.get("analysts", 0) >= 3 and recent(analyst.get("observed_at"), now, 7 * 24) else "partial" if analyst.get("analysts", 0) else "missing",
        f"{analyst.get('analysts', 0)} recommendations; source {analyst.get('source') or 'unavailable'}.", analyst.get("observed_at"))
    estimates = raw.get("estimates") or {}
    eps, rev = estimates.get("eps_periods", 0), estimates.get("revenue_periods", 0)
    inconsistent = estimates.get("inconsistent_periods", 0)
    add("estimates", "current" if eps and rev and not inconsistent and recent(estimates.get("observed_at"), now, 48) else "partial" if eps or rev else "stale" if estimates.get("observed_at") else "missing",
        f"Recent EPS/revenue fiscal periods: {eps}/{rev}; {inconsistent} inconsistent provider intervals. EPS accounting basis is unknown; do not compare with GAAP or adjusted guidance automatically.", estimates.get("observed_at"))
    days = estimates.get("observation_days", 0)
    add("revisions", "partial" if days >= 2 else "building" if days else "missing",
        f"{days} observed days, starting {estimates.get('first_observed_at') or 'unavailable'}. Daily snapshots retain first observation; provider retrospective trends are not historical snapshots.")
    disclosures = raw.get("disclosures") or {}
    add("disclosures", "observed" if disclosures.get("reports_90d") else "unknown",
        f"{disclosures.get('reports_90d', 0)} filings in 90 days; {disclosures.get('financial_reports', 0)} annual/quarterly reports. Filing counts do not prove complete collection.", disclosures.get("observed_at"))
    news = raw.get("news") or {}
    add("news", "observed" if news.get("articles_90d") else "unknown",
        f"{news.get('articles_7d', 0)} articles in 7 days; {news.get('articles_90d', 0)} in 90 days. One provider; no articles is not proof of no news.", news.get("observed_at"))
    guidance = raw.get("guidance") or {}
    pending, errors = disclosures.get("pending", 0), disclosures.get("errors", 0)
    add("guidance", "partial" if guidance.get("events_90d") else "pending" if pending or errors else "unknown",
        f"{guidance.get('events_90d', 0)} extracted ranges; {guidance.get('matched_consensus', 0)} matched event-time consensus; {pending} releases pending and {errors} parse failures. Only explicit annual narrative ranges are parsed.", guidance.get("observed_at"))
    add("actions", "partial" if raw.get("total_return_date") else "missing",
        f"Dividend-adjusted evaluation history through {raw.get('total_return_date') or 'unavailable'}. Separate dividend, split, merger and spin-off calendars are not collected.")
    add("calls", "not_collected", "No dedicated earnings-call transcript or investor-presentation collector; releases may contain some related information.")
    add("ownership", "not_collected", "Insider transaction values and institutional holding changes are not parsed.")
    add("macro", "not_collected", "No dedicated rates, inflation, economic-event or commodity-exposure feed.")
    gaps = [x["key"] for x in layers if x["status"] not in ("current", "observed")]
    return {"company_id": raw["company_id"], "ticker": raw["ticker"], "layers": layers,
            "gaps": gaps, "all_major_data_complete": False}


def summarize(companies):
    families = []
    for key, label in FAMILIES.items():
        counts = {}
        for company in companies:
            status = next(x["status"] for x in company["layers"] if x["key"] == key)
            counts[status] = counts.get(status, 0) + 1
        families.append({"key": key, "label": label, "status_counts": counts,
                         "covered_companies": counts.get("current", 0) + counts.get("observed", 0), "total": len(companies)})
    return families


def load_coverage(db, company_id=None, financial_report=None, now=None):
    if financial_report is None:
        reports = db.table("pipeline_runs").select("metadata,finished_at,status").eq("pipeline", "research_sources_refresh").contains("metadata", {"financial_audit": {}}).order("started_at", desc=True).limit(1).execute().data or []
        financial_report = next((r for r in reports if (r.get("metadata") or {}).get("financial_audit")), {})
    audit = ((financial_report.get("metadata") or {}).get("financial_audit") or {})
    by_id = {x["company_id"]: x for x in audit.get("companies", [])}
    raw = db.rpc("research_source_inventory", {"p_company_id": company_id}).execute().data or []
    companies = [company_coverage(r, by_id.get(r["company_id"]), financial_report.get("finished_at"), now) for r in raw]
    checks = db.table("pipeline_runs").select("pipeline,status,started_at,finished_at").in_("pipeline", ["research_sources_refresh", "company_disclosures_refresh", "estimate_consensus_refresh", "news_refresh", "sec_guidance_refresh", "analyst_consensus_refresh"]).order("started_at", desc=True).limit(40).execute().data or []
    latest = {}
    for check in checks:
        latest.setdefault(check["pipeline"], check)
    return {"companies": companies, "families": summarize(companies), "source_checks": list(latest.values()), "all_major_data_complete": False}
