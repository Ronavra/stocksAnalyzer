# stocksAnalyzer

AI-assisted S&P 500 research platform.

## MVP
- Web dashboard for market overview and research candidates
- S&P 500 company research pages
- Weekly research workflow
- Earnings and catalyst tracking
- Change detection between research snapshots
- API-first architecture ready for market data, Supabase, and an LLM research layer

## Architecture
- `apps/web`: Next.js frontend
- `services/api`: FastAPI backend
- `docs`: product/research specifications

## Run locally

### API
```bash
cd services/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Web
```bash
cd apps/web
npm install
npm run dev
```

Copy `.env.example` to `.env.local` / your backend environment and add credentials only when integrations are enabled.

## Research philosophy
The platform separates facts, market expectations, catalysts, risks, and scenario analysis. Scores are research signals, not personalized investment advice.
