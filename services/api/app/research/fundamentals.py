from dataclasses import dataclass

@dataclass
class FundamentalSignals:
    revenue_growth: float | None
    operating_margin: float | None
    operating_margin_change: float | None
    fcf_margin: float | None
    net_debt_to_fcf: float | None

def _ratio(a, b):
    if a is None or b in (None, 0): return None
    return float(a) / float(b)

def derive(latest: dict, previous: dict | None) -> FundamentalSignals:
    previous = previous or {}
    revenue_growth = None
    if latest.get("revenue") is not None and previous.get("revenue"):
        revenue_growth = float(latest["revenue"]) / float(previous["revenue"]) - 1
    margin = _ratio(latest.get("operating_income"), latest.get("revenue"))
    prev_margin = _ratio(previous.get("operating_income"), previous.get("revenue"))
    fcf_margin = _ratio(latest.get("free_cash_flow"), latest.get("revenue"))
    net_debt_to_fcf = None
    fcf = latest.get("free_cash_flow")
    if fcf and float(fcf) > 0:
        net_debt = float(latest.get("total_debt") or 0) - float(latest.get("cash") or 0)
        net_debt_to_fcf = net_debt / float(fcf)
    return FundamentalSignals(
        revenue_growth,
        margin,
        None if margin is None or prev_margin is None else margin-prev_margin,
        fcf_margin,
        net_debt_to_fcf,
    )

def score(signals: FundamentalSignals) -> float | None:
    values=[]
    if signals.revenue_growth is not None:
        values.append(max(0,min(100,50+signals.revenue_growth*250)))
    if signals.operating_margin is not None:
        values.append(max(0,min(100,40+signals.operating_margin*150)))
    if signals.operating_margin_change is not None:
        values.append(max(0,min(100,50+signals.operating_margin_change*500)))
    if signals.fcf_margin is not None:
        values.append(max(0,min(100,40+signals.fcf_margin*200)))
    if signals.net_debt_to_fcf is not None:
        values.append(max(0,min(100,75-signals.net_debt_to_fcf*10)))
    return None if not values else round(sum(values)/len(values),1)
