# Weekly five-day selection

The production selection ranks up to five qualifying companies using current
data. Prior selection does not exclude a company or reduce its score. The
primary objective is five trading days; 10/20-day forecasts and outcomes remain
separate measurements and do not get averaged into the ranking.

## Active financial policy

`financial-analyst-priority-v2` uses fixed user weights: **45% financial, 35% price
setup, 10% analyst consensus, 10% recent earnings surprise**. This is a research policy, not a fitted
or calibrated return forecast. Financial factors compare sector percentiles:
revenue/EPS growth, operating/net margins, operating-margin change, FCF margin
and conversion, net debt/FCF, earnings yield and FCF yield. Negative EPS is a
negative earnings yield, never a cheap negative P/E. Financial-sector companies
use growth, net margin/change and earnings yield; bank ROE and capital adequacy
are not currently covered by this limited profile.

Eligibility requires a full SEC audit within 48 hours, verification against the
latest official filing, a TTM period within 180 days and 80% weighted usable
financial-factor coverage. Revenue, net income and EPS are mandatory. Missing
factors retain their weights and earn no points. Sector factors require five
peers. Price setups need 50 observations; financial score must reach 50/100 and
combined score 55/100. Missing recent earnings is neutral 50, explicitly flagged.
There is no padding to five or rotation restriction.

Selection refreshes SEC/earnings checks, records factors, component contributions,
coverage, report dates and audit time, and preserves frozen older cohorts.
`--dry-run` previews without DB changes. New v7 cohorts use next-session-close
entry and 5/10/20-day evaluation by the daily cycle.

`refresh_analyst_consensus.py` collects the current universe daily and before
weekly selection. Without a Finnhub key it uses Yahoo Finance through pinned
yfinance (personal research, unofficial integration). If `FINNHUB_API_KEY` is
configured, it uses the official recommendation-trends endpoint; access and
coverage remain dependent on that account. No paid endpoint is activated.
Install `services/api/sql/analyst_consensus.sql` before running the new version.
This table is insert-only for the backend service role, with RLS and no public
client grants. Observations retain provider month and actual collection time
separately. Older monthly rows collected today are not historical knowledge.

The analyst score maps strong buy/buy/hold/sell/strong sell to 100/75/50/25/0,
averages the counts and shrinks toward 50 by N/(N+5). It needs three analysts,
capture within seven days and provider month within 45 days. Missing, invalid,
stale or thin coverage is neutral 50, explicitly flagged; its fixed 10% is not
redistributed. Current price targets are stored only on the current provider
month, displayed as supplementary evidence, and do not enter the score. Live
snapshots must precede the actual decision timestamp; historical replay requires
capture before that anchor's US market close. Backfilled rows never enter old
signals. Existing v6 (50/40/10) and older cohorts remain frozen.

Refresh reports separate successful execution from complete/partial coverage,
list missing/error counts and abort repeated source failures without inventing
data. Price/financial cycles continue with a flagged neutral analyst component.
The new collection starts now; no historical improvement for analyst weights
is claimed. The existing v1 replay describes the older financial-only policy.

`compare_financial_ranking.py` replays fixed weights against the previous screen
with filing-date availability, delayed entry, 0.2% costs and paired outcomes.
Missing selected outcomes exclude the paired week; cash weeks pay no stock
transaction costs. The last 20% is descriptive, not a new untouched test.
Financial backfills lack historical SEC audit snapshots, and constituents and
sectors are current. This replay cannot certify point-in-time improvement or
promote forecasts. Frozen forward results remain necessary.

## Separate price-model experiment

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
Selection cohorts whose delayed exits cross the final audit boundary are
purged before variant choice, so that choice is knowable at the first audit anchor.

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
job completed; promotion is computed separately. This experiment requires a passed
record with a matching protocol and validation/data no more than eight days
old, then refits on currently matured data and checks the latest feature date.
The fixed financial policy above is active; this experiment does not replace it
automatically. The older
probability model remains available in its own validation report, but its
selection-close labels do not validate next-session-entry forecasts. No old
frozen cohort is replaced.

Current constituents and sector classifications cause historical survivorship
bias. Historical catalyst adjustments may contain provider revisions; ranker
training does not use earnings/fundamental backfills. Close fills are proxies;
the downside percentile is not a stop or guaranteed loss bound. Audit reuse
can overfit repeated research, so frozen live outcomes must continue to be
tracked before confidence in the strategy increases.

## Live ledger

New v5/v6/v7 cohorts store the selection close separately and leave `entry_price`
empty until the next session closes. The daily evaluator fills that entry and
uses the same SPY session calendar. It evaluates 5/10/20 full trading days from
entry and deducts the 0.2% assumed round-trip cost. Older cohorts preserve their
original entry and evaluation policy. The web distinguishes selection price,
execution entry, gross ongoing return, and after-cost matured outcomes.

The weekly validation workflow runs Saturdays at 09:45 Asia/Jerusalem, with
manual dispatch and a push trigger for changes to the experiment. Daily and
weekly selection schedules remain unchanged. An unfinished/failed validation
does not promote a model.
