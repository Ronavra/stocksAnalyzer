from dataclasses import dataclass

@dataclass
class AnalystAssessment:
    research_score: float | None
    probability_up: float | None
    expected_return: float | None
    downside_return: float | None
    fair_value_low: float | None
    fair_value_base: float | None
    fair_value_high: float | None
    thesis_status: str
    confidence: str
    evidence_coverage: float
    thesis: list[str]
    risks: list[str]
    invalidation_conditions: list[str]
    model_version: str = "analyst-v0.1"

def build(snapshot: dict) -> AnalystAssessment:
    evidence=[]; risks=[]; invalidation=[]
    setup=snapshot.get("opportunity_score"); hist_up=snapshot.get("setup_probability_up")
    med=snapshot.get("setup_median_return_5d"); n=int(snapshot.get("setup_sample_size") or 0)
    drawdown=snapshot.get("setup_drawdown_60d"); upside=snapshot.get("upside_to_60d_high")
    fundamentals=snapshot.get("fundamentals_score"); earnings=snapshot.get("earnings_score")
    if hist_up is not None: evidence.append(f"Similar historical price setups were positive after 5 trading days {float(hist_up):.1%} of the time across {n} labeled observations.")
    if med is not None: evidence.append(f"Median 5-day return for similar historical setups was {float(med):+.1%}.")
    if drawdown is not None: evidence.append(f"Price is {abs(float(drawdown)):.1%} below its prior 60-day high.")
    if fundamentals is not None: evidence.append(f"Available fundamental signals score {float(fundamentals):.1f}/100.")
    if earnings is not None: evidence.append(f"Available estimate-revision signals score {float(earnings):.1f}/100.")
    if n < 50: risks.append("Limited number of comparable historical setups.")
    if fundamentals is None: risks.append("Full-universe fundamental evidence is not yet available.")
    if earnings is None: risks.append("Point-in-time analyst revision evidence is not yet available.")
    if snapshot.get("valuation_score") is None: risks.append("Validated fair-value model is not yet available.")
    invalidation=["Material deterioration in earnings/revenue expectations.","A new earnings or guidance event that changes the thesis.","Price behavior materially diverges from the historical setup."]
    coverage=sum(x is not None for x in [setup,hist_up,med,drawdown,upside,fundamentals,earnings])/7*100
    confidence="medium" if coverage>=70 and n>=100 else "low"
    return AnalystAssessment(float(setup) if setup is not None else None,None,None,None,None,None,None,
        "watch" if setup is not None else "insufficient_data",confidence,round(coverage,1),evidence,risks,invalidation)
