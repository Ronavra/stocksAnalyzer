from dataclasses import dataclass

@dataclass
class FundamentalSignals:
    revenue_growth: float | None
    operating_margin: float | None
    operating_margin_change: float | None
    fcf_margin: float | None
    net_debt_to_fcf: float | None

def _ratio(a,b):
    if a is None or b in (None,0): return None
    return float(a)/float(b)

def derive(latest: dict, previous: dict | None) -> FundamentalSignals:
    previous=previous or {}
    growth=None
    if latest.get("revenue") is not None and previous.get("revenue"):
        growth=float(latest["revenue"])/float(previous["revenue"])-1
    margin=_ratio(latest.get("operating_income"),latest.get("revenue"))
    prev_margin=_ratio(previous.get("operating_income"),previous.get("revenue"))
    fcf_margin=_ratio(latest.get("free_cash_flow"),latest.get("revenue"))
    leverage=None
    fcf=latest.get("free_cash_flow")
    if fcf and float(fcf)>0:
        leverage=(float(latest.get("total_debt") or 0)-float(latest.get("cash") or 0))/float(fcf)
    return FundamentalSignals(growth,margin,None if margin is None or prev_margin is None else margin-prev_margin,fcf_margin,leverage)

def score_general(s: FundamentalSignals) -> tuple[float|None,float]:
    metrics=[]
    def add(value):
        if value is not None: metrics.append(max(0,min(100,value)))
    add(None if s.revenue_growth is None else 50+s.revenue_growth*250)
    add(None if s.operating_margin is None else 40+s.operating_margin*150)
    add(None if s.operating_margin_change is None else 50+s.operating_margin_change*500)
    add(None if s.fcf_margin is None else 40+s.fcf_margin*200)
    add(None if s.net_debt_to_fcf is None else 75-s.net_debt_to_fcf*10)
    return (None if not metrics else round(sum(metrics)/len(metrics),1), round(len(metrics)/5*100,1))

def scoring_profile(company: dict) -> str:
    sector=(company.get("sector") or "").lower()
    industry=(company.get("industry") or "").lower()
    if "financial" in sector or "bank" in industry:
        return "bank"
    return "general"

def score(signals: FundamentalSignals, profile: str="general") -> tuple[float|None,float]:
    if profile=="bank":
        # Current generic statements lack bank-specific inputs (NIM, CET1, ROTCE,
        # credit quality). Do not manufacture a misleading score.
        return None,0.0
    return score_general(signals)
