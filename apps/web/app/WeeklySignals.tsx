import Link from "next/link";

type Signal = {
  id: number;
  signal_date: string;
  horizon_days: number;
  rank: number | null;
  entry_price: number | null;
  current_price: number | null;
  current_price_date: string | null;
  return_since_signal: number | null;
  research_score: number | null;
  historical_up_rate: number | null;
  historical_median_return: number | null;
  sample_size: number | null;
  model_probability_up: number | null;
  model_expected_return: number | null;
  model_diagnostics?: {ranking_mode?: string; selection_context?: {drawdown_60d?: number | null; upside_to_60d_high?: number | null}} | null;
  catalyst?: {reported_date?: string; surprise_percent?: number | null} | null;
  actual_return: number | null;
  excess_return: number | null;
  companies?: {ticker: string; name?: string; sector?: string | null} | null;
};

type Score = {evaluated: number; win_rate: number | null; avg_excess_return: number | null};
type Scorecard = {by_horizon?: Record<string, Score>};

const pct = (value: number | null | undefined, digits = 1) =>
  value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
const money = (value: number | null | undefined) =>
  value == null ? "—" : `$${Number(value).toFixed(2)}`;

export default function WeeklySignals({signals, scorecard}: {signals: Signal[]; scorecard: Scorecard}) {
  const dates = Array.from(new Set(signals.map(row => row.signal_date))).sort().reverse();
  const cohorts = dates.map(date => {
    const rows = signals.filter(row => row.signal_date === date);
    const tickers = Array.from(new Set(rows.map(row => row.companies?.ticker).filter((ticker): ticker is string => Boolean(ticker))));
    const stocks = tickers.map(ticker => {
      const horizons = rows.filter(row => row.companies?.ticker === ticker).sort((a, b) => a.horizon_days - b.horizon_days);
      return {ticker, horizons, main: horizons[0]};
    }).sort((a, b) => (a.main.rank ?? 99) - (b.main.rank ?? 99));
    return {date, stocks};
  });

  return <section className="panel" aria-label="Weekly research shortlist">
    <div className="panelHead"><div><p className="eyebrow">FROZEN RESEARCH SHORTLIST</p><h2>Weekly candidates</h2></div><p className="muted">Selected after a validated market close. The list stays frozen; only the latest price and evaluated results change.</p></div>
    <div className="scoreGrid">{[5, 10, 20].map(horizon => {
      const score = scorecard.by_horizon?.[String(horizon)];
      return <article key={horizon}><span>{horizon} trading days · observed results</span><strong>{score?.evaluated ? pct(score.win_rate) : "Pending"}</strong><small>{score?.evaluated ? `${score.evaluated} evaluated · ${pct(score.avg_excess_return)} average vs SPY` : "Waiting for matured signals"}</small></article>;
    })}</div>
    <p className="muted">A historical replay (2024–September 2026) trailed SPY over 5, 10 and 20 trading days. It uses current index members and backfilled earnings, so it is descriptive research rather than a validated forecast. <a href="https://github.com/Ronavra/stocksAnalyzer/actions/runs/36480208583">Review the replay</a>.</p>
    {cohorts.length ? cohorts.map((cohort, index) => {
      const previousTickers = new Set(cohorts[index + 1]?.stocks.map(stock => stock.ticker) ?? []);
      return <div className="weeklyCohort" key={cohort.date}>
        <div className="weeklyHead"><div><b>{index === 0 ? "Latest frozen shortlist" : "Earlier shortlist"}</b><span>Selection close: {cohort.date} · {cohort.stocks.length} of 5 qualified</span></div></div>
        {cohort.stocks.length < 5 && <p className="muted">Only {cohort.stocks.length} candidates passed the selection rules. No stocks were added to fill the list.</p>}
        <div className="weeklyCards">{cohort.stocks.map(({ticker, main, horizons}) => {
          const drawdown = main.model_diagnostics?.selection_context?.drawdown_60d;
          const repeat = previousTickers.has(ticker);
          const calibrated = main.model_diagnostics?.ranking_mode === "calibrated_blend";
          return <article className="weeklyStock" key={ticker}>
            <div className="weeklyStockHead"><span className="weeklyRank">#{main.rank}</span><Link href={`/company/${encodeURIComponent(ticker)}`} className="ticker">{ticker}</Link>{repeat && <small className="repeatTag">Also selected previously</small>}</div>
            <p className="stockName">{main.companies?.name ?? ""}</p>
            <p className="modelStatus">{calibrated ? "Validated model contributes to rank" : "Historical screen · no validated model forecast"}</p>
            <div className="weeklyEvidence"><b>Why it qualified</b><p>{main.sample_size ?? "—"} similar past setups · {pct(main.historical_up_rate)} rose over 5 trading days · median {pct(main.historical_median_return)}.</p>{main.catalyst?.reported_date && <small>Recent earnings reported {main.catalyst.reported_date}{main.catalyst.surprise_percent == null ? "" : ` · EPS surprise ${pct(main.catalyst.surprise_percent / 100)}`}</small>}</div>
            <div className="weeklyEvidence risk"><b>Risk to check</b><p>{drawdown != null && Number(drawdown) <= -0.1 ? `The signal close was ${pct(Math.abs(Number(drawdown)))} below its 60-day high. A rebound is uncertain.` : (main.sample_size ?? 0) < 100 ? "The historical match has fewer than 100 examples. Its observed win rate may be unstable." : "Similar past setups do not guarantee this stock will rise. Review company news and downside before acting."}</p></div>
            <div className="priceCompare"><div><small>Selection close · {cohort.date}</small><b>{money(main.entry_price)}</b></div><span>→</span><div><small>Latest close · {main.current_price_date ?? "—"}</small><b>{money(main.current_price)}</b></div></div>
            <div className="weeklyMeta"><span>Research rank score {main.research_score == null ? "—" : Number(main.research_score).toFixed(1)}</span><span className={main.return_since_signal == null ? "" : main.return_since_signal >= 0 ? "positive" : "negative"}>Since selection {pct(main.return_since_signal)}</span></div>
            <div className="horizonGrid">{horizons.map(horizon => <div key={horizon.id} className={`horizon ${horizon.actual_return == null ? "pending" : "done"}`}><b>{horizon.horizon_days} days</b><span>{horizon.model_probability_up == null ? "No validated P↑" : `Model P↑ ${pct(horizon.model_probability_up)}`}</span>{horizon.model_expected_return != null && <small>Model expected {pct(horizon.model_expected_return)}</small>}<small>{horizon.actual_return == null ? "Outcome pending" : `Observed ${pct(horizon.actual_return)}`}</small>{horizon.excess_return != null && <small>{pct(horizon.excess_return)} vs SPY</small>}</div>)}</div>
          </article>;
        })}</div>
      </div>;
    }) : <p className="muted">No shortlist has passed the validated weekly freeze yet.</p>}
    <p className="muted">A stock may appear again in a later week. Historical setup rates are descriptive and are not model probabilities.</p>
  </section>;
}
