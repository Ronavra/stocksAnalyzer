from .models import ScoreBreakdown

WEIGHTS = {
    "fundamentals": 0.25,
    "valuation": 0.15,
    "earnings": 0.20,
    "momentum": 0.10,
    "news": 0.15,
    "catalysts": 0.15,
}

def composite_score(scores: ScoreBreakdown) -> float:
    values = scores.model_dump()
    return round(sum(values[k] * weight for k, weight in WEIGHTS.items()), 1)
