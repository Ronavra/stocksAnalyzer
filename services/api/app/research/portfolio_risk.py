"""Research-only allocation experiments. Frozen production picks are never edited."""
from collections import defaultdict
from .portfolio_comparison import positive
from .observations import timestamp


def weights_for(rows, method, sector_cap=.4, published_at=None):
    if method not in ("equal_sector_cap","inverse_volatility_sector_cap"):
        raise ValueError("Unknown portfolio experiment")
    if not 0<sector_cap<=1: raise ValueError("Invalid sector cap")
    contexts={r["company_id"]:(r.get("model_diagnostics") or {}).get("selection_context") or {} for r in rows}
    if len(contexts)!=len(rows): raise ValueError("Duplicate frozen picks")
    if any(not c.get("sector") or not c.get("observed_at") for c in contexts.values()):
        return None,"sector_not_frozen_at_publication"
    cutoff=timestamp(published_at)
    if published_at and (cutoff is None or any(timestamp(c["observed_at"]) is None or timestamp(c["observed_at"])>cutoff for c in contexts.values())):
        return None,"risk_snapshot_after_publication"
    raw={}
    for cid,context in contexts.items():
        vol=positive(context.get("volatility_20d"))
        if method=="inverse_volatility_sector_cap" and vol is None:
            return None,"volatility_not_frozen_at_publication"
        raw[cid]=1/vol if method=="inverse_volatility_sector_cap" else 1.
    if not raw: return {},None
    total=sum(raw.values());weights={cid:value/total for cid,value in raw.items()}
    sectors=defaultdict(list)
    for cid,context in contexts.items(): sectors[context["sector"]].append(cid)
    for ids in sectors.values():
        allocation=sum(weights[cid] for cid in ids)
        if allocation>sector_cap:
            for cid in ids: weights[cid]*=sector_cap/allocation
    # Capped capital stays in cash; it is never silently redistributed or borrowed.
    return weights,None
