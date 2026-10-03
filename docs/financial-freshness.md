# SEC financial freshness

A successful source refresh confirms retrieval, not complete or current financial statements.
Every full SEC refresh now compares extracted periods and TTM availability with the company's
latest 10-Q/10-K (including amendments), 20-F or 40-F in the official submissions feed.

The audit is saved in `pipeline_runs.metadata.financial_audit`, exposed by `/api/v1/research/data-audit`
and displayed on the home page. SEC-only runs also upload `sec-financial-quality` in Actions.
The summary separates latest-filing coverage, the 180-day TTM period-age limit, and eight-field
coverage. A current period can still have missing revenue, EPS, cash flow, cash, debt or shares.
The eight-field checklist is generic; bank analysis requires sector-specific measures.

Extraction merges supported standard tags across filing dates, accepts discrete quarters disclosed
in annual filings, and uses actual duration dates rather than the filing's fiscal-period label.
Bank total revenue net of interest takes precedence over contract-fee revenue. Cash flow is derived
from cumulative statements only where the matching preceding cumulative period was already filed.
An annual statement is itself a TTM observation. Rolling TTM requires consecutive quarters and
preserves reported Q4 and annual values. Missing cash/debt components are not filled with zero.

Daily SEC-derived valuation excludes TTM periods older than 180 days and companies whose latest
full-refresh audit could not verify the current filing. Invalid derived snapshots for the latest
price date are removed when rebuilding that date. Previously stored historical snapshots remain.

Remaining limits: SEC Company Facts does not expose all custom company tags; the current extractor
uses USD US-GAAP fields. New entities may have insufficient TTM history. A missing field is not zero,
and a company's most recent annual filing can legitimately be older than the valuation age limit.
Guidance and broad analyst-estimate coverage are separate sources and are not implied by this audit.
No financial factor or model is promoted by a successful ingestion run.
