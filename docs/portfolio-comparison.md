# Portfolio comparison with SPY

`GET /api/v1/research/portfolio-comparison` replays frozen publications into a
USD 10,000 paper portfolio. Every selection policy and 5/10/20-session holding
period is a separate account. It never edits recommendations or promotes a model.

## Execution and capital

Entry is the first regular market close after both the signal date and the actual
publication timestamp. Scheduled NYSE early closes count as 13:00 Eastern.
Legacy recommendation ledgers retain their original measurements; this replay
does not grant an execution price before publication.

Each account has `ceil(horizon/5)` equal initial capital sleeves. A funded group
invests its sleeve equally across all its frozen picks, holds for its stated
number of market sessions after entry, then sells. Proceeds stay in that sleeve
and fund its next group. Exits precede entries at the same close. If every sleeve
is committed, an extra group is recorded as unfunded. No-pick groups and idle
sleeves remain in zero-yield cash. There is no leverage or assumed extra capital.

Base/stress scenarios charge 0.10%/0.25% of each traded notional at every buy and
sell. These are assumptions, not broker quotes. Buy-and-hold SPY pays the same
entry-side cost. Open holdings on both sides are marked to the close, without
an assumed final liquidation. Taxes are excluded.

## Return bases and data quality

Price-only results use canonical split-adjusted market prices. Total-return
results use **separate** Twelve Data `time_series?adjust=all` evaluation series,
with split/dividend adjustments representing reinvestment. These adjusted levels
are not valuation prices, execution quotes, or point-in-time training inputs.

Apply `services/api/sql/portfolio_return_series.sql` once to initialize the
service-role-only, RLS-enabled table. The hosted and independent daily schedulers
then run `scripts/refresh_portfolio_returns.py`. Only frozen recommendation
companies and SPY are fetched, with a bounded request budget and a freshness
cache. A complete adjusted series is replaced atomically per company to avoid
mixing adjustment vintages after corporate actions. Endpoint access denial is
recorded as incomplete coverage, without requesting a paid upgrade.

`scripts/check_portfolio_comparison.py` records a dated summary in the
`portfolio_comparison` pipeline. The independent Portfolio Return Evaluation
workflow refreshes and verifies the comparison on relevant code changes or manual
dispatch, without waiting for the market-research queue. Daily schedulers also
verify after collection. Each company snapshot is atomic; a concurrent refresh
cannot splice differently adjusted bars into one stored series.

The replay uses expected NYSE sessions, not the number of downloaded bars.
Missing entry/held-company/benchmark closes and incomplete frozen groups block
the comparison at the last complete day. Total-return results never fall back
to price-only results. The API marks stale market data and returns the precise
missing dates/companies.

## Interpretation

The dashboard shows the capital curves, cumulative net returns, their difference,
daily maximum drawdown, costs, cash and funded/closed/unfunded groups. Short-lived
accounts are not annualized; CAGR requires at least 365 calendar days. Selection
policies remain separate. Open positions contribute unrealized gains/losses.

Positive observed excess is not evidence of a repeatable advantage. The next
research stage needs point-in-time data, frozen alternatives, out-of-sample
comparison and sufficient forward outcomes, including risk and cost stress tests.
