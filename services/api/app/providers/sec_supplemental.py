"""Explicit consolidated financial aliases; custom facts need exact semantics."""
from datetime import date
from math import isfinite

BALANCE_TAGS = {
    "equity": ("StockholdersEquity",),
    "assets": ("Assets",),
    "preferred_equity": ("PreferredStockValue", "PreferredStockCarryingValue"),
    "short_term_borrowings": ("ShortTermBorrowings", "ShortTermDebt"),
    "current_debt": ("DebtCurrent",),
    "long_term_debt_total": ("LongTermDebtCurrentAndNoncurrent", "LongTermDebtAndFinanceLeaseObligations"),
}
CAPITAL_TAGS = {
    "cet1_ratio": ("CommonEquityTier1CapitalRatio", "CommonEquityTier1RiskBasedCapitalRatio", "CommonEquityTier1CapitalToRiskWeightedAssets"),
    "tier1_ratio": ("TierOneRiskBasedCapitalRatio", "Tier1RiskBasedCapitalRatio", "Tier1CapitalRatio"),
    "total_capital_ratio": ("TotalRiskBasedCapitalRatio", "TotalCapitalRatio"),
    "leverage_ratio": ("TierOneLeverageCapitalRatio", "Tier1LeverageRatio", "Tier1LeverageCapitalRatio"),
}


def supplemental_by_period(data):
    out = {}
    for field, tags in {**BALANCE_TAGS, **CAPITAL_TAGS}.items():
        # Custom capital aliases can be present only in a vetted filing instance.
        namespaces = ("us-gaap", "bank-capital") if field in CAPITAL_TAGS else ("us-gaap",)
        for namespace in namespaces:
            facts = (data.get("facts") or {}).get(namespace) or {}
            for priority, tag in enumerate(tags):
                units = (facts.get(tag) or {}).get("units") or {}
                for row in units.get("pure" if field in CAPITAL_TAGS else "USD", []):
                    if not row.get("end") or not row.get("filed") or row.get("start"):
                        continue
                    if row.get("form") not in ("10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A"):
                        continue
                    try:
                        value = float(row["val"])
                    except (ValueError, TypeError, KeyError):
                        continue
                    if not isfinite(value) or (field in CAPITAL_TAGS and not 0 <= value <= 1):
                        continue
                    target = out.setdefault(row["end"], {})
                    previous = target.get(field)
                    key = (row["filed"], -priority)
                    if previous is None or key >= (previous["filed_date"], -previous["alias_priority"]):
                        target[field] = {"value": value, "tag": tag, "namespace": namespace,
                                         "filed_date": row["filed"], "accession_number": row.get("accn"),
                                         "alias_priority": priority, "basis": row.get("capital_basis", "consolidated")}
    return out


def attach_supplemental(rows, data):
    facts = supplemental_by_period(data)
    for row in rows:
        values = {k: v for k, v in facts.get(row["period_end"], {}).items()
                  if v["filed_date"] <= (row.get("filed_date") or "")}
        row["supplemental"] = values
        if row.get("reported_debt_basis"):
            values["debt_basis"]=row["reported_debt_basis"]
        # Recover an explicitly reported full long-term total plus short-term
        # borrowing. Do not add DebtCurrent, which includes current maturities.
        long_debt = values.get("long_term_debt_total")
        short_debt = values.get("short_term_borrowings")
        if row.get("total_debt") is None and long_debt and short_debt:
            row["total_debt"] = long_debt["value"] + short_debt["value"]
            values["debt_basis"] = "reported_long_term_total_plus_short_term_borrowings"
    return rows
