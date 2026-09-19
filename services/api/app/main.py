from fastapi import FastAPI

app = FastAPI(title="StocksAnalyzer API", version="0.1.0")

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/api/v1/research/framework")
def research_framework():
    return {
        "steps": [
            "what_happened",
            "why_investors_care",
            "time_horizon",
            "financial_metrics_affected",
            "market_assumptions",
            "scenarios",
            "catalysts_and_risks",
            "thesis_change",
        ]
    }
