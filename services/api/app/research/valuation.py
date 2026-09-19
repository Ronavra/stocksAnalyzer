from dataclasses import dataclass

@dataclass
class ValuationSignals:
    market_cap: float | None
    price: float | None
    pe: float | None
    price_to_fcf: float | None
    fcf_yield: float | None

def derive(quote: dict, latest: dict) -> ValuationSignals:
    market_cap=quote.get("marketCap")
    price=quote.get("price")
    eps=latest.get("eps_diluted")
    fcf=latest.get("free_cash_flow")
    pe=None
    if price is not None and eps is not None and float(eps)>0:
        pe=float(price)/float(eps)
    pfcf=None
    fcf_yield=None
    if market_cap is not None and fcf is not None and float(fcf)>0:
        pfcf=float(market_cap)/float(fcf)
        fcf_yield=float(fcf)/float(market_cap)
    return ValuationSignals(market_cap,price,pe,pfcf,fcf_yield)

def score(s: ValuationSignals) -> tuple[float|None,float]:
    metrics=[]
    if s.pe is not None:
        metrics.append(max(0,min(100,90-s.pe*1.5)))
    if s.price_to_fcf is not None:
        metrics.append(max(0,min(100,90-s.price_to_fcf*1.5)))
    return (None if not metrics else round(sum(metrics)/len(metrics),1),round(len(metrics)/2*100,1))
