# Predictive data and twenty-session research

Source recovery uses free, bounded public observations. A CSV failure for one
FRED series does not disable other series. Official Fed dollar, EIA WTI and
FRED observation tables are current captures, never fabricated ALFRED vintages.
BLS timed monthly release tables can replace an unavailable ICS feed. GDP
freshness includes its quarterly publication lag.

EPS accounting basis is accepted only from explicit provider metadata. GAAP,
adjusted/non-GAAP and conflicting or unknown labels stay distinct. Currency
and interval checks retain provenance in `estimate_snapshots.normalization`.
An issuer's GAAP results never establish the basis of an analyst forecast.
Old immutable observations are not rewritten or backdated. Unknown basis can
still leave EPS revisions unavailable; collection coverage is not usable-model
coverage.

Free upcoming ex-dividend observations are retained from the existing Yahoo
earnings-calendar response, without additional issuer requests. Missing dates
are unknown; a payment date is not used as an ex-dividend date. Historical
Yahoo dividend/split checks and these projected dividends form the free action
audit. Comprehensive future split, merger and spin-off calendars remain
unavailable. Paid Twelve Data calendar calls require explicit
`ENABLE_TWELVE_ACTIONS_CALENDAR=true`; ordinary price collection is independent.

Source coverage uses the same bounded aggregate RPC as the dashboard, retaining
all company/family coverage while avoiding repeated expensive inventories.
Alternate allowlisted issuer pages can recover a blocked IR index; an observed
fallback is recorded and unsupported call/transcript coverage remains visible.
