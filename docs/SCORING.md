# Scoring model v0.1
The composite score prioritizes research; it is not a buy/sell rating.

| Factor | Weight |
|---|---:|
| Fundamentals | 25% |
| Valuation | 15% |
| Earnings / revisions | 20% |
| Momentum | 10% |
| News / sentiment | 15% |
| Catalysts | 15% |

Live factors must retain timestamps and provenance. Missing inputs must not silently become neutral scores. Event risk is separate from attractiveness. We will backtest factor definitions before treating the composite as decision-useful.
