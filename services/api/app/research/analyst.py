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
    catalyst: dict | None = None
    model_version: str = "analyst-v0.2"

def _pct(v):
    return f"{float(v):+.1f}%" if v is not None else None

def build(snapshot: dict, latest_earnings: dict | None = None) -> AnalystAssessment:
    evidence=[]; risks=[]
    setup=snapshot.get("opportunity_score"); hist_up=snapshot.get("setup_probability_up")
    med=snapshot.get("setup_median_return_5d"); n=int(snapshot.get("setup_sample_size") or 0)
    drawdown=snapshot.get("setup_drawdown_60d"); upside=snapshot.get("upside_to_60d_high")
    fundamentals=snapshot.get("fundamentals_score"); revisions=snapshot.get("earnings_score")
    catalyst=None
    if latest_earnings:
        eps=latest_earnings.get("surprise_percent"); rev=latest_earnings.get("revenue_surprise_percent")
        eps_beat=eps is not None and float(eps)>0; rev_beat=rev is not None and float(rev)>0
        catalyst={"reported_date":latest_earnings.get("reported_date"),"eps_surprise_pct":eps,
                  "revenue_surprise_pct":rev,"eps_beat":eps_beat if eps is not None else None,
                  "revenue_beat":rev_beat if rev is not None else None,
                  "source":latest_earnings.get("source")}
        parts=[]
        if eps is not None: parts.append(f"EPS surprise {_pct(eps)}")
        if rev is not None: parts.append(f"revenue surprise {_pct(rev)}")
        if parts: evidence.append(f"Latest reported earnings ({latest_earnings.get('reported_date')}): "+", ".join(parts)+".")
        if eps is not None and rev is not None and eps_beat and rev_beat:
            evidence.append("Latest earnings showed confirmation across both EPS and revenue versus consensus.")
        elif eps is not None and rev is not None and (not eps_beat) and (not rev_beat):
            risks.append("Latest earnings missed consensus on both EPS and revenue.")
        elif eps is not None and rev is not None:
            risks.append("Latest earnings were mixed across EPS and revenue versus consensus.")
    if hist_up is not None: evidence.append(f"Similar historical price setups were positive after 5 trading days {float(hist_up):.1%} of the time across {n} labeled observations.")
    if med is not None: evidence.append(f"Median 5-day return for similar historical setups was {float(med):+.1%}.")
    if drawdown is not None: evidence.append(f"Price is {abs(float(drawdown)):.1%} below its prior 60-day high.")
    if fundamentals is not None: evidence.append(f"Available fundamental signals score {float(fundamentals):.1f}/100.")
    if revisions is not None: evidence.append(f"Available estimate-revision signals score {float(revisions):.1f}/100.")
    if n < 50: risks.append("Limited number of comparable historical setups.")
    if fundamentals is None: risks.append("Full-universe fundamental evidence is not yet available.")
    if revisions is None: risks.append("Point-in-time analyst revision evidence is not yet available.")
    if snapshot.get("valuation_score") is None: risks.append("Validated fair-value model is not yet available.")
    risks.append("Earnings surprises are catalyst evidence, not a calibrated probability forecast; recent walk-forward tests did not beat the direction baseline consistently.")
    invalidation=["Material deterioration in earnings/revenue expectations.","A new earnings or guidance event that changes the thesis.","Price behavior materially diverges from the historical setup."]
    fields=[setup,hist_up,med,drawdown,upside,fundamentals,revisions,latest_earnings]
    coverage=sum(x is not None for x in fields)/len(fields)*100
    confidence="medium" if coverage>=70 and n>=100 else "low"
    return AnalystAssessment(float(setup) if setup is not None else None,None,None,None,None,None,None,
        "watch" if setup is not None else "insufficient_data",confidence,round(coverage,1),evidence,risks,invalidation,catalyst)
