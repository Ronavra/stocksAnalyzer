from dataclasses import dataclass

@dataclass
class EventSignals:
    eps_surprise_pct: float|None
    revenue_surprise_pct: float|None
    guidance_eps_vs_consensus: float|None
    guidance_revenue_vs_consensus: float|None
    eps_guidance_change: float|None
    revenue_guidance_change: float|None

def _mid(lo,hi):
    if lo is None and hi is None: return None
    if lo is None: return float(hi)
    if hi is None: return float(lo)
    return (float(lo)+float(hi))/2

def _rel(a,b):
    if a is None or b in (None,0): return None
    return float(a)/abs(float(b))-1

def derive(earnings:dict|None,guidance:dict|None)->EventSignals:
    e=earnings or {}; g=guidance or {}
    eps_mid=_mid(g.get("eps_guidance_low"),g.get("eps_guidance_high"))
    rev_mid=_mid(g.get("revenue_guidance_low"),g.get("revenue_guidance_high"))
    prev_eps=_mid(g.get("previous_eps_guidance_low"),g.get("previous_eps_guidance_high"))
    prev_rev=_mid(g.get("previous_revenue_guidance_low"),g.get("previous_revenue_guidance_high"))
    return EventSignals(
      e.get("surprise_percent"),e.get("revenue_surprise_percent"),
      _rel(eps_mid,g.get("consensus_eps_at_event")),_rel(rev_mid,g.get("consensus_revenue_at_event")),
      _rel(eps_mid,prev_eps),_rel(rev_mid,prev_rev))
