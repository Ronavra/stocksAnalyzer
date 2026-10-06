"""The database owns the Sunday publication clock for every scheduler."""
import json


def publication_due(db, signal_date):
    result = db.rpc("recommendation_publication_status", {
        "p_signal_date": signal_date,
    }).execute().data
    if not isinstance(result, dict) or result.get("status") not in (
        "due", "not_due", "already_published",
    ):
        raise RuntimeError(f"Recommendation publication blocked: {result}")
    if result["status"] != "due":
        print("Recommendation publication skipped:", json.dumps(result), flush=True)
        return False
    return True
