from enum import Enum
from pydantic import BaseModel, Field

class Signal(str, Enum):
    priority = "priority"
    watch = "watch"
    neutral = "neutral"

class ScoreBreakdown(BaseModel):
    fundamentals: float = Field(ge=0, le=100)
    valuation: float = Field(ge=0, le=100)
    earnings: float = Field(ge=0, le=100)
    momentum: float = Field(ge=0, le=100)
    news: float = Field(ge=0, le=100)
    catalysts: float = Field(ge=0, le=100)

class CompanyResearch(BaseModel):
    ticker: str
    company: str
    sector: str
    score: float
    signal: Signal
    catalyst: str
    scores: ScoreBreakdown
    what_changed: str
    market_assumption: str
