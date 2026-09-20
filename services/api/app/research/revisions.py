from dataclasses import dataclass
from datetime import date, timedelta

@dataclass
class RevisionTrend:
    eps_7d: float|None; eps_30d: float|None; eps_90d: float|None
    revenue_7d: float|None; revenue_30d: float|None; revenue_90d: float|None
    coverage: float

def _num(v):
    try: return float(v) if v is not None else None
    except (TypeError,ValueError): return None

def _change(now,old):
    a,b=_num(now),_num(old)
    if a is None or b in (None,0): return None
    return a/b-1

def derive(rows:list[dict], as_of:date|None=None)->RevisionTrend:
    """Point-in-time revisions for one fiscal target. Rows must contain captured_date
    plus consensus fields. Uses only snapshots known on/before as_of."""
    as_of=as_of or date.today()
    usable=[r for r in rows if date.fromisoformat(str(r["captured_date"]))<=as_of]
    usable.sort(key=lambda r:r["captured_date"])
    latest=usable[-1] if usable else {}
    def prior(days):
        cutoff=as_of-timedelta(days=days)
        candidates=[r for r in usable if date.fromisoformat(str(r["captured_date"]))<=cutoff]
        return candidates[-1] if candidates else {}
    p7,p30,p90=prior(7),prior(30),prior(90)
    vals=[
      _change(latest.get("eps_consensus"),p7.get("eps_consensus")),
      _change(latest.get("eps_consensus"),p30.get("eps_consensus")),
      _change(latest.get("eps_consensus"),p90.get("eps_consensus")),
      _change(latest.get("revenue_consensus"),p7.get("revenue_consensus")),
      _change(latest.get("revenue_consensus"),p30.get("revenue_consensus")),
      _change(latest.get("revenue_consensus"),p90.get("revenue_consensus"))]
    return RevisionTrend(*vals,round(sum(v is not None for v in vals)/6*100,1))
