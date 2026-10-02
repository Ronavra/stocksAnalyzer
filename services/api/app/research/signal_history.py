def complete_oldest_signal_cohort(db,rows):
    """A row limit must not make the last visible shortlist look incomplete."""
    if not rows:
        return rows
    oldest=min(row["signal_date"] for row in rows)
    complete=(db.table("research_predictions").select("*,companies(ticker,name,sector)")
              .eq("signal_date",oldest).order("rank").execute().data or [])
    return [row for row in rows if row["signal_date"]!=oldest]+complete
