# stocksAnalyzer

AI-assisted S&P 500 research platform.

For a smaller Supabase database with full historical research kept on the API computer, see [local market history setup](docs/local-market-history.md).

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

macOS / Linux:
```bash
cd services/api
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Windows PowerShell (run from the repository root):
```powershell
cd services/api
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

After pulling backend updates, reinstall `requirements.txt` with the same virtual-environment Python before restarting the API. The explicit `tzdata` dependency supplies IANA time zones on Windows, which does not provide a system IANA database.

### Web
```bash
cd apps/web
npm ci
npm run dev
```

Copy `.env.example` to `.env.local` / your backend environment and add credentials only when integrations are enabled.

## Independent daily refresh on Windows

After updating the API requirements, run this once from `services/api` on your Windows host:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_schedule.ps1
```

The task uses your existing API environment and runs at 08:00 Israel time. Windows must use **Israel Standard Time**, and the host must be on with your user signed in. Supabase independently records whether the daily market refresh finished by noon.

## Research philosophy
The platform separates facts, market expectations, catalysts, risks, and scenario analysis. Scores are research signals, not personalized investment advice.

See [reliability and history repair](docs/reliability.md) for publication guarantees, data quality checks, scheduling and remaining research limitations.

See [portfolio comparison with SPY](docs/portfolio-comparison.md) for capital allocation,
publication-aware execution, dividends, costs and benchmark measurement rules.
