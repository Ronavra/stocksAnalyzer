"""Information availability is the later of publication and first observation."""
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo


def close_cutoff(day):
    return datetime.combine(datetime.fromisoformat(day).date(), time(16), ZoneInfo("America/New_York"))


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        return None


def available(row, cutoff, observed_key="observed_at", published_key="published_at"):
    cutoff = timestamp(cutoff) if isinstance(cutoff, str) else cutoff
    observed = timestamp(row.get(observed_key))
    published = timestamp(row.get(published_key)) if row.get(published_key) else observed
    return bool(cutoff and observed and published and max(observed, published) <= cutoff)


def financial_versions(rows, cutoff=None):
    """Collapse only versions actually seen by the cutoff, never today's rows."""
    chosen = {}
    for version in rows:
        if cutoff is not None and not available(version, cutoff):
            continue
        row = version.get("snapshot") or {}
        if row.get("period_type") != "ttm" or not row.get("filed_date"):
            continue
        key = (version["company_id"], version["period_end"])
        if key not in chosen or version["observed_at"] > chosen[key]["observed_at"]:
            chosen[key] = {**row, "observed_at": version["observed_at"], "provenance": version.get("provenance")}
    return list(chosen.values())


def member_asof(memberships, company_id, day):
    return any(r["company_id"] == company_id and r["effective_from"] <= day
               and (not r.get("effective_to") or day < r["effective_to"])
               and (not r.get("captured_at") or timestamp(r["captured_at"]) is not None and timestamp(r["captured_at"])<=close_cutoff(day))
               for r in memberships)


def earnings_versions(rows, cutoff):
    chosen={}
    for version in rows:
        if not available(version,cutoff):
            continue
        key=version["event_id"]
        if key not in chosen or version["observed_at"]>chosen[key]["observed_at"]:
            chosen[key]={**version["snapshot"],"observed_at":version["observed_at"]}
    return list(chosen.values())
