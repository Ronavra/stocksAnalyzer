"""Current fiscal estimates; relative Yahoo labels never become guessed dates."""
from datetime import date, datetime
from hashlib import sha256
import json
import math


def number(value):
    if isinstance(value, dict):
        value = value.get("raw")
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def scalar(value):
    return value.get('raw') if isinstance(value,dict) else value


def accounting_basis(record,eps):
    aliases={'gaap':'gaap','us-gaap':'gaap','non-gaap':'adjusted','non gaap':'adjusted','adjusted':'adjusted','normalized':'adjusted'}
    evidence=[]
    for container,label in ((eps,'earningsEstimate'),(record,'record')):
        for key in ('epsBasis','accountingBasis'):
            raw=scalar(container.get(key))
            if isinstance(raw,str) and raw.strip().lower() in aliases:
                evidence.append((aliases[raw.strip().lower()],label+'.'+key,raw))
    values={x[0] for x in evidence}
    if len(values)!=1:
        return 'unknown',{'reason':'conflicting_explicit_basis' if values else 'provider_does_not_state_basis'}
    return evidence[0][0],{'field':evidence[0][1],'label':evidence[0][2]}


def currency(value):
    value=scalar(value)
    return value.strip().upper() if isinstance(value,str) and len(value.strip())==3 and value.strip().isalpha() else None


def normalize(company_id, records, observed_at):
    today = datetime.fromisoformat(observed_at.replace("Z", "+00:00")).date()
    rows = {}
    for record in records:
        relative = record.get("period")
        if relative not in ("0q", "+1q", "0y", "+1y"):
            continue
        try:
            # endDate comes from the provider's earningsTrend record. A
            # calendar quarter guessed from 0q would be wrong for many issuers.
            period_end = date.fromisoformat(str(record.get("endDate")))
        except ValueError:
            continue
        if not -180 <= (period_end - today).days <= 800:
            continue
        eps = record.get("earningsEstimate") or {}
        revenue = record.get("revenueEstimate") or {}
        eps_avg, rev_avg = number(eps.get("avg")), number(revenue.get("avg"))
        if eps_avg is None and rev_avg is None:
            continue
        basis,basis_evidence=accounting_basis(record,eps)
        row = {"company_id": company_id, "captured_date": today.isoformat(),
               "fiscal_period_end": period_end.isoformat(),
               "period_type": "quarter" if relative.endswith("q") else "annual",
               "relative_period": relative, "eps_consensus": eps_avg,
               "revenue_consensus": rev_avg, "eps_basis": basis,
               "normalization": {"version":"explicit-basis-v1","basis_evidence":basis_evidence,"issues":[]},
               "eps_currency": currency(eps.get("earningsCurrency") or eps.get("currency")),
               "revenue_currency": currency(revenue.get("revenueCurrency") or revenue.get("currency")),
               "source": "yahoo_finance", "captured_at": observed_at}
        for kind, values in (("eps", eps), ("revenue", revenue)):
            low, high = number(values.get("low")), number(values.get("high"))
            # Preserve the average, but reject an internally reversed interval.
            if low is not None and high is not None and low > high:
                low = high = None
            count = number(values.get("numberOfAnalysts"))
            row.update({f"{kind}_low": low, f"{kind}_high": high,
                        f"{kind}_analyst_count": int(count) if count is not None and count >= 0 and count.is_integer() else None})
        for metric in ('eps','revenue'):
            avg=row.get(metric+'_consensus');low=row.get(metric+'_low');high=row.get(metric+'_high')
            if avg is not None and ((low is not None and avg<low) or (high is not None and avg>high)):
                row['normalization']['issues'].append(metric+'_consensus_outside_interval')
            if row.get(metric+'_currency') is None:
                row['normalization']['issues'].append(metric+'_currency_unknown')
        if basis=='unknown':row['normalization']['issues'].append('eps_basis_unknown')
        # These are provider-reported retrospectives observed TODAY, not a
        # backfilled point-in-time archive of past estimates.
        row["provider_eps_trend"] = {k: number(v) for k, v in (record.get("epsTrend") or {}).items()}
        row["provider_eps_revisions"] = {k: number(v) for k, v in (record.get("epsRevisions") or {}).items()}
        identity = json.dumps(row, sort_keys=True, separators=(",", ":"))
        row["source_record_id"] = sha256(identity.encode()).hexdigest()
        rows[(row["fiscal_period_end"], row["period_type"])] = row
    return list(rows.values())


class EstimateConsensusProvider:
    source = "yahoo_finance"

    def fetch(self, ticker):
        import yfinance as yf
        company = yf.Ticker(ticker.replace(".", "-"))
        # The public API fetches estimates. Its DataFrame drops fiscal endDate,
        # so retain it from the same response cached by the pinned adapter.
        company.get_earnings_estimate()
        records = getattr(company._analysis, "_earnings_trend", None)
        if not isinstance(records, list):
            raise RuntimeError("Yahoo estimate response has no fiscal-period metadata")
        return records
