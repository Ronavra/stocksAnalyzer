from .models import CompanyResearch, ScoreBreakdown, Signal
from .scoring import composite_score

# Seed data is deliberately labeled demo. Live providers replace this layer next.
SEED = [
    ("NVDA","NVIDIA","Information Technology","AI demand / estimates",(91,48,92,83,82,88)),
    ("MSFT","Microsoft","Information Technology","Cloud + AI monetization",(88,61,85,72,78,82)),
    ("AMZN","Amazon","Consumer Discretionary","AWS / margin trajectory",(84,66,82,74,73,78)),
    ("AVGO","Broadcom","Information Technology","AI networking demand",(87,54,89,79,77,84)),
    ("XOM","Exxon Mobil","Energy","Oil / refining environment",(80,74,70,64,76,79)),
    ("JPM","JPMorgan Chase","Financials","Rates / credit quality",(86,68,77,67,72,70)),
]

def _build(row):
    ticker, company, sector, catalyst, raw = row
    scores = ScoreBreakdown(
        fundamentals=raw[0], valuation=raw[1], earnings=raw[2],
        momentum=raw[3], news=raw[4], catalysts=raw[5],
    )
    score = composite_score(scores)
    signal = Signal.priority if score >= 80 else Signal.watch if score >= 70 else Signal.neutral
    return CompanyResearch(
        ticker=ticker, company=company, sector=sector, score=score, signal=signal,
        catalyst=catalyst, scores=scores,
        what_changed="Demo research snapshot; live evidence pipeline not connected yet.",
        market_assumption="Placeholder until estimates, filings, valuation and news providers are connected.",
    )

COMPANIES = [_build(row) for row in SEED]
