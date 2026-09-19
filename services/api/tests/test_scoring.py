from app.scoring import calculate_composite_score
from app.models import ScoreBreakdown

def test_composite_score_weighting():
    scores = ScoreBreakdown(
        fundamentals=80,
        valuation=70,
        earnings=90,
        momentum=60,
        news=75,
        catalysts=85,
    )
    assert calculate_composite_score(scores) == 79.75
