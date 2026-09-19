# Data pipeline

## Goal
Replace demo research scores with source-backed S&P 500 research inputs.

## Pipeline
1. Sync the S&P 500 universe from a licensed/reliable constituent source.
2. Fetch price/market data.
3. Fetch statements and normalized financial metrics.
4. Ingest SEC filings as primary-source evidence.
5. Ingest earnings, estimates/revisions, catalysts and news.
6. Preserve provider, source URL and capture timestamp for every live input.
7. Compute factor scores only when required inputs are present.
8. Persist weekly research snapshots for change detection.

## Guardrails
- Missing data is missing, never silently neutral.
- Facts, consensus estimates, model interpretation and scenarios remain distinct.
- Writes happen on the backend with server credentials.
- Provider adapters isolate vendor-specific APIs.
- S&P membership must be timestamped because index composition changes.
