from app.models import ScoreBreakdown
from app.scoring import composite_score
from app.research.fundamentals import FundamentalSignals, score

def test_composite_score_weighting():
    scores=ScoreBreakdown(fundamentals=80,valuation=70,earnings=90,momentum=60,news=75,catalysts=85)
    assert composite_score(scores)==78.5

def test_general_fundamentals_reports_coverage():
    signals=FundamentalSignals(0.10,0.20,0.01,0.15,1.0)
    value,coverage=score(signals,"general")
    assert value is not None
    assert coverage==100.0

def test_bank_score_is_withheld_without_bank_metrics():
    signals=FundamentalSignals(0.10,0.20,0.01,0.15,1.0)
    value,coverage=score(signals,"bank")
    assert value is None
    assert coverage==0.0
