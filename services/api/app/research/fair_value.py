from dataclasses import dataclass

@dataclass
class FairValueRange:
    low: float|None; base: float|None; high: float|None
    method: str; coverage: float

def earnings_multiple(price, forward_eps, peer_pe_low, peer_pe_median, peer_pe_high):
    """Scenario valuation, not a price target. Multiples must come from a validated
    comparable-company or historical-relative process; missing inputs stay missing."""
    vals=[forward_eps,peer_pe_low,peer_pe_median,peer_pe_high]
    if any(v is None for v in vals):
        return FairValueRange(None,None,None,"forward_eps_relative_multiple",0.0)
    eps=float(forward_eps)
    if eps<=0: return FairValueRange(None,None,None,"forward_eps_relative_multiple",0.0)
    low,base,high=eps*float(peer_pe_low),eps*float(peer_pe_median),eps*float(peer_pe_high)
    return FairValueRange(round(low,2),round(base,2),round(high,2),"forward_eps_relative_multiple",100.0)

def implied_upside(price, value):
    if price in (None,0) or value is None: return None
    return float(value)/float(price)-1
