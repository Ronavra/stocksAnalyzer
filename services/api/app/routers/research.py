from fastapi import APIRouter, HTTPException
from ..data import COMPANIES

router = APIRouter(prefix="/api/v1/research", tags=["research"])

@router.get("/candidates")
def candidates():
    return sorted(COMPANIES, key=lambda x: x.score, reverse=True)

@router.get("/companies/{ticker}")
def company(ticker: str):
    match = next((x for x in COMPANIES if x.ticker == ticker.upper()), None)
    if not match:
        raise HTTPException(status_code=404, detail="Ticker not found")
    return match

@router.get("/framework")
def framework():
    return {"steps":["what_happened","why_investors_care","time_horizon","financial_metrics_affected","market_assumptions","scenarios","catalysts_and_risks","thesis_change"]}
