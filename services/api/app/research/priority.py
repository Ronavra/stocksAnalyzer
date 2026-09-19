from dataclasses import dataclass

@dataclass
class PriorityResult:
    score: float | None
    coverage: float
    reason: str

def calculate(snapshot: dict, previous: dict | None = None) -> PriorityResult:
    """Prioritize what deserves research, not what deserves buying."""
    previous=previous or {}
    components=[]; reasons=[]

    fundamentals=snapshot.get("fundamentals_score")
    if fundamentals is not None:
        # Extreme/strong fundamentals can be research-worthy, but this is a
        # smaller input than actual change signals.
        components.append((abs(float(fundamentals)-50)*2,0.25))
        reasons.append(f"fundamentals {float(fundamentals):.1f}")

    earnings=snapshot.get("earnings_score")
    if earnings is not None:
        components.append((abs(float(earnings)-50)*2,0.40))
        reasons.append(f"estimate revisions {float(earnings):.1f}")

    current_pe=snapshot.get("pe"); previous_pe=previous.get("pe")
    if current_pe is not None and previous_pe not in (None,0):
        change=abs(float(current_pe)/float(previous_pe)-1)
        components.append((min(100,change*500),0.20))
        reasons.append(f"P/E changed {change:.1%}")

    current_pfcf=snapshot.get("price_to_fcf"); previous_pfcf=previous.get("price_to_fcf")
    if current_pfcf is not None and previous_pfcf not in (None,0):
        change=abs(float(current_pfcf)/float(previous_pfcf)-1)
        components.append((min(100,change*500),0.15))
        reasons.append(f"P/FCF changed {change:.1%}")

    if not components:
        return PriorityResult(None,0.0,"No comparable research signals yet")
    available_weight=sum(w for _,w in components)
    score=sum(v*w for v,w in components)/available_weight
    return PriorityResult(round(score,1),round(available_weight*100,1),"; ".join(reasons))
