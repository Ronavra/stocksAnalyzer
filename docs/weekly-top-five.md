# Weekly five-day selection

The production selection ranks up to five qualifying companies using current
data. Prior selection does not exclude a company or reduce its score. The
primary objective is five trading days; 10/20-day forecasts and outcomes remain
separate measurements and do not get averaged into the ranking.

## Experiment

`validate_weekly_ranker.py` runs cross-sectional excess-return regression,
absolute-return regression and a separate 10th-percentile absolute-return regression. Features are the existing
price and market/sector context fields. Each weekly cross-section has equal
training weight. There are two fixed variants: expected excess return, and
expected excess minus 25% of estimated downside magnitude. Only positive
expected excess, positive ranking score, and at least 80% input coverage qualify.
Predicted absolute return must also exceed the assumed 0.2% round-trip cost, so
positive relative performance alone cannot qualify a predicted losing stock.
There is no padding or company/sector rotation rule.

Selection occurs after the week's last market close. Execution is approximated
by the *next* trading session's close; exit is five further trading sessions
later. Training uses only outcomes whose actual delayed exit preceded its
anchor. Retraining happens every 13 evaluated weeks. The first 60% of matured
weekly dates provides initial history; the next 20% selects the fixed variant;
the final 20% independently audits that chosen variant. The model can expand
its training history during the audit, using only labels matured at each fit.

The comparison screen reproduces the setup/catalyst fallback with the same
input-coverage universe and delayed-entry dates. A missing outcome for a stock
already selected excludes the entire paired cohort, never the stock before
selection. Excluded and attempted cohorts are reported. Cash/no-pick weeks
remain in the comparison and pay no transaction cost.

## Promotion

Both the selection and final audit require at least 26 paired weeks and 95%
evaluation coverage. Net return, excess versus SPY, improvement versus the
screen, and excess under a 0.5% round-trip cost scenario must be positive.
One-sided 95% lower bounds of paired improvement versus the screen and SPY
must be positive, using deterministic four-week circular block resampling.
The worst 20% of weekly returns must not be worse than the screen, and the
observed lower-decile forecast breach rate must fall between 5% and 20%.

These are fixed research criteria, not optimized thresholds or investment
guarantees. Costs of 0.2% and 0.5% are scenarios, not real broker fees. SPY is
compared gross, making the after-cost excess test conservative. Validation
records and an artifact contain all results and limitations. Success means the
job completed; promotion is computed separately. Production requires a passed
record with a matching protocol and validation/data no more than eight days
old, then refits on currently matured data and checks the latest feature date.
If the weekly ranker fails, the existing gated five-day probability model or
historical screen is retained. No old frozen cohort is replaced.

Current constituents and sector classifications cause historical survivorship
bias. Historical catalyst adjustments may contain provider revisions; ranker
training does not use earnings/fundamental backfills. Close fills are proxies;
the downside percentile is not a stop or guaranteed loss bound. Audit reuse
can overfit repeated research, so frozen live outcomes must continue to be
tracked before confidence in the strategy increases.

## Live ledger

New v5 cohorts store the selection close separately and leave `entry_price`
empty until the next session closes. The daily evaluator fills that entry and
uses the same SPY session calendar. It evaluates 5/10/20 full trading days from
entry and deducts the 0.2% assumed round-trip cost. Older cohorts preserve their
original entry and evaluation policy. The web distinguishes selection price,
execution entry, gross ongoing return, and after-cost matured outcomes.

The weekly validation workflow runs Saturdays at 09:45 Asia/Jerusalem, with
manual dispatch and a push trigger for changes to the experiment. Daily and
weekly selection schedules remain unchanged. An unfinished/failed validation
does not promote a model.
