"""Use the rebuilt valuation for the candidate's own market close."""


def current_valuations(db, candidates):
    dates={r["company_id"]:r.get("price_date") for r in candidates if r.get("price_date")}
    if not dates:
        return {}
    rows=(db.table("valuation_snapshots").select("company_id,snapshot_date,pe,price_to_fcf")
          .eq("source","sec_price_derived").in_("company_id",list(dates))
          .in_("snapshot_date",sorted(set(dates.values()))).execute().data or [])
    return {r["company_id"]:r for r in rows if dates.get(r["company_id"])==r["snapshot_date"]}
