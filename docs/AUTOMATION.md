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

Never commit API keys to the repository.

## Daily workflow
The daily workflow updates Twelve Data price history, rebuilds price features, rescans the S&P 500 setups, evaluates matured frozen forecasts, and writes results to Supabase.

## Weekly workflow
The weekly workflow evaluates any matured forecasts and freezes the Top 5 research signals at 5, 10, and 20 trading-day horizons.

## Auditability
weekly-signal-v1 stays immutable as a model version while live evidence accumulates. Future rule changes should use a new model version.
