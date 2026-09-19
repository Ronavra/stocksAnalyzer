from dataclasses import dataclass

@dataclass
class ValuationSignals:
    market_cap: float | None
    price: float | None
    pe: float | None
    price_to_fcf: float | None
    fcf_yield: float | None

def derive(quote: dict, latest: dict) -> ValuationSignals:
    market_cap=quote.get("marketCap"); price=quote.get("price")
    eps=latest.get("eps_diluted"); fcf=latest.get("free_cash_flow")
    pe=float(price)/float(eps) if price is not None and eps is not None and float(eps)>0 else None
    pfcf=float(market_cap)/float(fcf) if market_cap is not None and fcf is not None and float(fcf)>0 else None
    fy=float(fcf)/float(market_cap) if market_cap is not None and fcf is not None and float(market_cap)>0 else None
    return ValuationSignals(market_cap,price,pe,pfcf,fy)

def score(s: ValuationSignals) -> tuple[float|None,float]:
    # Store raw valuation signals now; do not pretend a universal absolute
    # multiple is comparable across sectors/business models.
    available=sum(x is not None for x in (s.pe,s.price_to_fcf))
    return None,round(available/2*100,1)
