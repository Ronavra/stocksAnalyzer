# Major stock data coverage

The dashboard's data-family inventory and each company page separate current
data, observed events, stale data, incomplete fields, pending extraction and
uncollected sources. Record existence and a successful pipeline are not proof
of complete coverage or predictive value. Source collection attempts appear
separately; a failed latest attempt is not replaced by an older success.

## Collected sources

| Family | Collection and limitations |
| --- | --- |
| Price, volume and technical context | Daily OHLCV and price features, including derived market/sector context. Expected NYSE session dates determine freshness. |
| Financial statements | SEC annual, quarterly and TTM metrics, with original filings and first-observed revisions. Audit checks the latest filing, extraction and missing fields. Bank capital metrics remain missing when unreported/unparsed. |
| Valuation | Latest daily valuation; availability does not imply every multiple is meaningful for every industry. |
| Earnings | Historical actuals, EPS/revenue surprises and upcoming report dates/estimates. Future event dates can change. |
| Analyst recommendations | Daily observations of recommendation consensus; separate from EPS/revenue forecasts. |
| Fiscal EPS/revenue estimates | Yahoo Finance's current and next quarter/year observations, actual provider fiscal end dates, averages, ranges, counts and currencies. Unknown EPS accounting basis is retained. |
| Estimate revisions | First observation per UTC day/issuer/fiscal period/source is immutable. A same-day retry reuses it. Changes can only compare observed days with the same issuer, period, source, currency and basis. Provider 7/30/60/90-day retrospective EPS trends are stored as observations today, not backdated history. |
| Official filings | Independently checks SEC submissions for all active constituents; retains annual/quarterly reports, current reports, proxy materials and beneficial-ownership filing links. Ownership trade values are not parsed. |
| News | Massive company-tagged articles and source-attributed sentiment, with publication and observation timestamps. One provider is not all news; zero articles does not mean no event. |
| Management guidance | Explicit annual narrative EPS/revenue ranges from official releases. Ambiguous tables, quarterly ranges, withdrawn guidance and unknown accounting bases are not guessed. Event-time consensus remains unavailable unless independently recorded and comparable. |
| Corporate actions | Dividend/split-adjusted series for published portfolio evaluation. No dedicated dividend, split, merger or spin-off calendar yet. |

## Uncollected or incomplete major families

- Earnings-call transcripts and investor presentations lack a dedicated collector.
- Structured insider transaction values and institutional holding changes are
  not collected. Official beneficial-ownership links alone do not fill this gap.
- Rates, inflation, economic-event calendars and company-specific commodity or
  currency exposures lack dedicated feeds.
- Historical index membership before September 2026, discontinued securities,
  and long point-in-time analyst/financial revisions remain incomplete.
- Sector-specific KPIs and reported bank capital ratios remain partial.

These gaps remain explicit rather than being counted as complete because some
information may appear in news or an official release. No overall percentage
claims to include every factor influencing a stock.

## Operation

Apply `services/api/sql/research_source_inventory.sql` once with the other
service-only schema migrations. No browser access to raw provider tables is
granted. The read-only inventory function is SECURITY INVOKER and service-only.

`refresh_enrichment.py` runs fiscal estimates, news, official filing metadata,
vendor guidance, SEC range extraction and a persisted coverage audit. Each
source is independent; failures retain successful observations, appear in the
source's own pipeline and mark the enrichment run incomplete. Both the hosted
daily workflow and the independent scheduler already call this entry point.
The standalone Research Enrichment workflow also runs after relevant main
changes and SEC refreshes. It does not publish recommendations or promote a
model. No additional paid subscription is activated.

Estimate collection uses the public yfinance fetch and fiscal metadata retained
in the same response by the pinned yfinance adapter. Missing metadata is an
explicit failure, never a guessed quarter-end date. Repeated provider failures
stop the batch and retain a retryable partial report. Empty symbols are listed.

Official filing metadata preserves the original first-observed timestamp on
retries and verifies CIK identity before accepting a submission. Its bounded
lookback is 90 days and a recent successful check is reused only for the same
universe. SEC release downloads cap decoded input at 32 MB and visible text at
2 million characters; images/scripts/styles are discarded before range parsing.
Failed releases remain retryable and are visible in the inventory.

`check_source_coverage.py` records summary counts and source checks in
`pipeline_runs` as `source_coverage_audit`. A successful audit means the inventory
was computed; `all_major_data_complete` and `validated_predictive_value` remain
false. New source collection does not change the frozen ranking weights or
establish an advantage over SPY.
