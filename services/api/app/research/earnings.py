from dataclasses import dataclass

@dataclass
class RevisionSignals:
    revenue_revision: float | None
    eps_revision: float | None

def _revision(new,old):
    if new is None or old in (None,0): return None
    return float(new)/float(old)-1

def derive(latest: dict, previous: dict | None) -> RevisionSignals:
    previous=previous or {}
    return RevisionSignals(
        _revision(latest.get("estimated_revenue"),previous.get("estimated_revenue")),
        _revision(latest.get("estimated_eps"),previous.get("estimated_eps")),
    )

def score(s: RevisionSignals) -> tuple[float|None,float]:
    values=[]
    if s.revenue_revision is not None:
        values.append(max(0,min(100,50+s.revenue_revision*1000)))
    if s.eps_revision is not None:
        values.append(max(0,min(100,50+s.eps_revision*750)))
    return (None if not values else round(sum(values)/len(values),1),round(len(values)/2*100,1))
