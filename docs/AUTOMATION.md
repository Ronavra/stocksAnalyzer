# Automated operations

StocksAnalyzer uses GitHub Actions so the research database can refresh without a local computer.

## Schedule
- Daily Market Research: Monday-Friday at 17:37 America/New_York, after the regular market close.
- Weekly Signal Freeze: Friday at 20:17 America/New_York, after the daily refresh has had time to finish.
- Both workflows also support manual runs from GitHub Actions.

## Required GitHub Actions repository secrets
Add these under repository Settings > Secrets and variables > Actions:
- SUPABASE_URL
- SUPABASE_SERVICE_ROLE_KEY
- TWELVE_DATA_API_KEY
- MASSIVE_API_KEY (optional for the daily price cycle, used by catalyst-aware signal generation)
- SEC_USER_AGENT (for the SEC filings refresh): identify the application or organization and provide a monitored contact email, for example `StocksAnalyzer research-app admin@your-domain.example`. Set this to your own real address; the checked-in fallback contains only the project URL and may be denied by SEC.

Never commit API keys to the repository.

## Daily workflow
The daily workflow updates Twelve Data price history, rebuilds price features, rescans the S&P 500 setups, evaluates matured frozen forecasts, and writes results to Supabase. It then refreshes Massive earnings before SEC filings and valuation. SEC access failures still fail the source refresh and remain visible in `pipeline_runs`; the earlier market and earnings writes are preserved.

## Weekly workflow
The weekly workflow refreshes Massive earnings independently of SEC access, evaluates any matured forecasts, and freezes the Top 5 research signals at 5, 10, and 20 trading-day horizons. A successful earnings-only refresh is stored as `earnings_refresh` and does not count as a successful full `research_sources_refresh`.

If the SEC returns 403, verify the configured User-Agent and its contact address. If it still refuses the request, identify the runner IP to SEC webmaster through its published access guidance. Do not assume the missing fundamentals have been loaded or silence the source error.

## Auditability
weekly-signal-v1 stays immutable as a model version while live evidence accumulates. Future rule changes should use a new model version.
