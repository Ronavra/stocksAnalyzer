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
| Official filings | Independently checks SEC submissions for all active constituents; retains annual/quarterly reports, current reports, proxy materials and beneficial-ownership filing links. Form 4 is collected for structured transaction parsing. A separate bounded five-year inventory backfill follows older issuer SEC JSON files, preserving original dates and today's first collection; it covers current constituents, not historical membership. |
| News | Massive company-tagged articles and source-attributed sentiment, with publication and observation timestamps. One provider is not all news; zero articles does not mean no event. |
| Management guidance | Explicit fiscal-year and explicitly fiscal-labelled quarter narrative EPS/revenue ranges from official releases. Ambiguous tables, withdrawn guidance and unknown accounting bases are not guessed. Event-time consensus remains unavailable unless independently recorded and comparable. |
| Corporate actions | Dividend/split-adjusted series for published portfolio evaluation. Public two-year dividend/split history is collected independently. An optional Twelve Data calendar paginates US instruments and matches the active universe. Ex-dates are not publication dates; merger/spin-off coverage remains incomplete. |

## Uncollected or incomplete major families

- Dedicated original-document collection now supports an explicit MSFT/NVDA IR registry, HTML and text PDFs. The company registry and archive backfill queue remain incomplete; missing dates and OCR-only PDFs stay unknown.
- Form 4 transactions and current public institutional holdings are collected. Original institutional 13F verification, manager identity mapping, amendment-aware holding changes and long ownership history remain incomplete.
- Nine FRED series and BLS calendar snapshots are collected. Fed/BEA calendars and issuer-specific currency/commodity exposures remain incomplete. Without FRED_API_KEY, current CSV history is not past-known vintage data; configured ALFRED retrieval preserves vintage dates.
- Historical index membership before September 2026, discontinued securities,
  and long point-in-time analyst/financial revisions remain incomplete.
- Sector-specific KPIs and reported bank capital ratios remain partial.

These gaps remain explicit rather than being counted as complete because some
information may appear in news or an official release. No overall percentage
claims to include every factor influencing a stock.

## Operation

Apply `services/api/sql/research_evidence.sql` before
`services/api/sql/research_source_inventory.sql` with the other
service-only schema migrations. No browser access to raw provider tables is
granted. The read-only inventory function is SECURITY INVOKER and service-only.

`refresh_enrichment.py` runs fiscal estimates, news, official filing metadata,
Form 4 transactions, original documents, public holdings/actions, optional
corporate-action calendars, macro, vendor guidance, SEC range extraction and
a persisted coverage audit. Each
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
An average outside the provider's reported low/high interval marks the issuer's
estimate coverage partial. The source value is retained and flagged; revision
percentages involving that interval are suppressed rather than silently repaired.

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

## Source access and historical backfill

`refresh_company_disclosures.py --lookback-days 1825` follows older official SEC
inventory files. The Official Filing History Backfill workflow runs when first
installed and can be dispatched again. Form 4 rows stay within 90 days to avoid
flooding the daily queue; duplicate filings preserve their first observation.

`config/investor_relations.json` is an explicit issuer/domain registry. Expand
it with verified issuer sites. Allowlisted redirects cannot escape its hosts.
The known MSFT call date uses conservative end-of-publication-day availability,
not an invented precise intraday timestamp. Scanned PDFs stay unavailable.
Source bodies are capped at 200,000 stored characters and truncation is explicit.

Form 4 preserves joint owners, derivatives, codes, amendments and footnotes.
Code P means open-market **or private** purchase. A joint filing does not create
one transaction per owner. Public institutional holdings retain their report
date separately from observation time and do not establish original 13F
publication or historical availability. No subscription is purchased.

Add FRED_API_KEY to server/runner configuration for ALFRED observation versions.
Current CSV values retain observation time and cannot enter a historical test
as values known before collection. BLS calendars retain full immutable schedule
snapshots; the API selects the last successful snapshot and excludes removed
events. Schedules and collection failures remain visible separately.

For historical estimates/index data, require a vendor sample with stable issuer
and security identifiers, fiscal period, currency, accounting basis, original
availability time, revisions, index entries/exits and removed securities.
Verify the sample against original sources before import. A five-year price
chart of current constituents is not an unbiased five-year evaluation.

Financial diagnostics retain original XBRL identity contexts and capital tags.
Explicit parent-company/Standardized capital contexts are accepted; subsidiary
figures, regulatory minimums and unknown dimensions are excluded. Bank required
fields are checked separately from the generic eight-field inventory. Identity
transitions and insufficient TTM histories remain explicit.

Fiscal transition filings (10-KT/10-QT) are retained. When a year-end change
breaks the normal four-quarter construction, dollar TTM flows may be recovered
only through identities of exact reported start/end intervals using one
concept/unit, with availability bounded by the source filing. Missing intervals
and conflicting overlaps reject the calculation. Short transition periods are
never treated as twelve-month annual results. Diluted EPS is not derived by
this interval fallback because its denominator changes between periods.

### Originating macro sources during FRED outages

A failed FRED CSV HTTP request opens a circuit for the remainder of the collector run. Six current series have official originating-agency fallbacks: New York Fed EFFR (`DFF`), Treasury 2/10-year par yields (`DGS2`/`DGS10`), and BLS seasonally adjusted CPI (`CUSR0000SA0`), unemployment (`LNS14000000`) and nonfarm payrolls (`CES0000000001`). Treasury/BLS bulk responses are reused within a run. These observations retain their agency source and actual capture time, with no invented vintage date. GDP, broad dollar and WTI remain unavailable if FRED is inaccessible; current agency responses do not fill ALFRED historical-vintage coverage.
