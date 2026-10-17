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

See [major stock data coverage](docs/data-coverage.md) for collected sources,
daily estimate snapshots, company-specific gaps and uncollected data families.


## Loading dashboard fixes in a local checkout

After `git pull --ff-only`, stop and restart both the API and web development
servers. Run `npm ci` in `apps/web` if dependencies changed. The API's `/health`
response includes `selection_version` and `system_health_protocol`; the compact
health implementation reports `snapshot-v1`. An already-running API in another
checkout continues serving its old code until restarted. Database/workflow
updates do not restart a process on your Windows computer.


## Model improvement and validation

The production shortlist keeps one fixed 45/35/10/10 policy. The v6 research
model tests each additional evidence family against the same price/context
baseline, chooses features using the middle chronological period, and retains a
separate final promotion gate. Actual captured fiscal estimates and analyst
snapshots are now research inputs. Unknown EPS accounting bases and unmatched
currencies never become comparable revisions. No provider retrospective trend is
backdated into the observation archive.

Apply `services/api/sql/model_readiness.sql` before the updated
`services/api/sql/dashboard_health.sql` on a new project. Both are operational
service-only functions. The dashboard shows archive deferral, captured history,
interrupted training and current fiscal-estimate coverage separately from model
validation. A hosted workflow that cannot read the archive records a deferral.

On the Windows archive computer, after pulling and restarting the API/web:

```powershell
cd services/api
.\.venv\Scripts\python.exe scripts/run_local_model_validation.py
powershell -ExecutionPolicy Bypass -File scripts/install_windows_model_schedule.ps1
```

The task now runs Saturday at 14:00 Israel time, after Friday's close. Reinstall
it once to update an existing Friday task. The local daily scheduler also checks
for missed weekly research. The verified archive must be configured in the
existing `.env`, and the computer must be running with your account signed in.
The runner checks archive integrity, current market completeness, bounded
financial field repair, model validation and portfolio risk research. It has a
5.5-hour execution budget; database leases prevent overlapping training and
expire abandoned attempts after six hours. Expired workers cannot publish.

Financial field repair rotates through at most 25 issuers per batch, revisiting
unresolved companies after seven days. It inspects up to five original filings
per issuer, records remaining gaps, and never invents missing financial values.
Verified recovered TTM fields survive a later Company Facts omission only when
period, source, accession and filing date match exactly. A new/amended filing
must supply its own evidence.

Risk experiments compare a 40% sector cap and inverse-volatility sizing with the
frozen equal-weight portfolio. Capped capital stays in cash. Sector and daily
volatility are captured at future publications; missing old snapshots block the
experiment rather than substituting today's classification. Experiments do not
change published picks or add selection-policy controls. Their results are
research observations, not evidence of an advantage from a handful of weeks.
