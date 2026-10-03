"""Evaluate new execution-aware signals while preserving the old ledger policy."""

from app.research.weekly_rank_metrics import number


def execution_update(signal, prices, calendar=None):
    diagnostics = dict(signal.get("model_diagnostics") or {})
    horizon = signal["horizon_days"]
    delayed = diagnostics.get("entry_policy") == "next_session_close"
    required = horizon + (1 if delayed else 0)
    if delayed:
        if not prices or calendar == []:
            return {}, None
        entry_date = calendar[0] if calendar is not None else prices[0]["price_date"]
        lookup = {p["price_date"]: p for p in prices}
        entry = number((lookup.get(entry_date) or {}).get("close"))
        diagnostics["execution_entry_date"] = entry_date
        update = {"entry_price": entry, "model_diagnostics": diagnostics}
    else:
        entry = number(signal.get("entry_price"))
        entry_date = signal["signal_date"]
        update = {}
    if entry is None or entry <= 0:
        return {}, None
    if len(calendar if delayed and calendar is not None else prices) < required:
        return update, None
    if delayed and calendar is not None:
        exit_row = lookup.get(calendar[required - 1])
        if exit_row is None:
            return update, None
    else:
        exit_row = prices[required - 1]
    exit_price = number(exit_row.get("close"))
    if exit_price is None or exit_price <= 0:
        return update, None
    gross = exit_price / entry - 1
    cost = number(diagnostics.get("round_trip_cost")) or 0.
    diagnostics["gross_return"] = gross
    if delayed:
        update["model_diagnostics"] = diagnostics
    update.update({"exit_date": exit_row["price_date"], "exit_price": exit_price,
                   "actual_return": gross - cost, "correct_direction": gross - cost > 0})
    return update, entry_date
