import Link from "next/link";
import AnalystConsensus from "./AnalystConsensus";
import type {AnalystConsensus as Consensus, Cohort as CohortRecord} from "@/lib/api";

type PriceWindow = {price: number | null; date: string | null; status: "complete" | "pending" | "missing" | "calendar_unavailable"};

type Signal = {
  id: number;
  signal_date: string;
  horizon_days: number;
  rank: number | null;
  entry_price: number | null;
  exit_price?: number | null;
  exit_date?: string | null;
  recommendation_price?: number | null;
  recommendation_price_date?: string | null;
  change_since_recommendation?: number | null;
  trading_days_elapsed?: number | null;
  price_windows?: Record<string, PriceWindow>;
  current_price: number | null;
  current_price_date: string | null;
  return_since_signal: number | null;
  research_score: number | null;
  historical_up_rate: number | null;
  historical_median_return: number | null;
  sample_size: number | null;
  model_probability_up: number | null;
  model_expected_return: number | null;
  model_diagnostics?: {
    ranking_mode?: string;
    upcoming_earnings?:{reported_date:string;event_time?:string|null;within_horizons:number[];date_status:string}|null;
    entry_policy?: string;
    execution_entry_date?: string;
    selection_close?: number | null;
    weekly_ranker?: {expected_excess_5d?: number; downside_p10_5d?: number; feature_coverage?: number} | null;
    analyst_consensus?:Consensus|null;
    financial_ranking?: {score:number;coverage:number;profile:string;period_end:string;filed_date:string;audit_checked_at:string;
      weights:{financial:number;technical:number;earnings:number;analyst?:number};contributions:{financial:number;technical:number;earnings:number;analyst?:number};
      technical_score:number;earnings_score:number;earnings_available:boolean;
      factors:Record<string,{value:number|null;score:number|null;weight:number;contribution:number}>} | null;
    selection_context?: {drawdown_60d?: number | null; upside_to_60d_high?: number | null};
  } | null;
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
const factorNames:Record<string,string>={revenue_growth:"Revenue growth",eps_growth:"EPS growth",operating_margin:"Operating margin",net_margin:"Net margin",operating_margin_change:"Operating margin change",net_margin_change:"Net margin change",fcf_margin:"FCF margin",cash_conversion:"Cash conversion",net_debt_to_fcf:"Net debt / FCF",earnings_yield:"Earnings yield",fcf_yield:"FCF yield"};

function PriceCell({price, date}: {price: number | null | undefined; date: string | null | undefined}) {
  return <><b className="closePrice">{money(price)}</b><small className="priceDate">{date ?? "Date unavailable"}</small>{price == null && <small className="priceMissing">Price unavailable</small>}</>;
}

function WindowCell({window, elapsed, horizon}: {window?: PriceWindow; elapsed?: number | null; horizon: number}) {
  if (window?.status === "complete") return <PriceCell price={window.price} date={window.date}/>;
  if (window?.status === "pending") return <><span className="pricePending">Pending</span><small className="priceDate">{Math.min(elapsed ?? 0, horizon)} / {horizon} trading days</small></>;
  return <><span className="priceMissing">{window?.status === "missing" ? "Price missing" : "Data unavailable"}</span><small className="priceDate">{window?.date ?? "Check data health"}</small></>;
}

export default function WeeklySignals({signals, scorecard, cohortRecords=[]}: {signals: Signal[]; scorecard: Scorecard; cohortRecords?:CohortRecord[]}) {
  const dates = Array.from(new Set([...signals.map(row => row.signal_date),...cohortRecords.filter(row=>row.status==="no_picks").map(row=>row.signal_date)])).sort().reverse();
  const cohorts = dates.map(date => {
    const rows = signals.filter(row => row.signal_date === date);
    const tickers = Array.from(new Set(rows.map(row => row.companies?.ticker).filter((ticker): ticker is string => Boolean(ticker))));
    const stocks = tickers.map(ticker => {
      const horizons = rows.filter(row => row.companies?.ticker === ticker).sort((a, b) => a.horizon_days - b.horizon_days);
      return {ticker, horizons, main: horizons[0]};
    }).sort((a, b) => (a.main.rank ?? 99) - (b.main.rank ?? 99));
    return {date, stocks,record:cohortRecords.find(row=>row.signal_date===date)};
  });

  return <section className="panel" aria-label="Weekly research shortlist">
    <div className="panelHead"><div><p className="eyebrow">WEEKLY PRICE TRACKER</p><h2>Recommended stocks</h2></div><p className="muted">Latest recommendations below. Open an earlier group to see its prices.</p></div>
    <p className="timelineNote">Closing prices in USD. Windows count 5, 10 and 20 trading days after the recommendation date.</p>
    {cohorts.length ? cohorts.map((cohort, index) => {
      const previousTickers = new Set(cohorts[index + 1]?.stocks.map(stock => stock.ticker) ?? []);
      const Cohort = index === 0 ? "section" : "details";
      return <Cohort className={index === 0 ? "latestCohort" : "cohortAccordion"} key={cohort.date}>
        {index === 0 ? <div className="latestCohortHead"><span className="cohortLabel"><b>Latest recommendations · {cohort.date}</b><small>{cohort.stocks.length} stocks</small></span></div> : <summary><span className="cohortLabel"><b>Week of {cohort.date}</b><small>{cohort.stocks.length} stocks</small></span><span className="accordionChevron" aria-hidden="true">⌄</span></summary>}
        <div className="cohortBody">
          {cohort.record?.status==="no_picks"&&<p className="muted">No stocks met the selection requirements this week. The recorded decision is to stay in cash.</p>}
          <div className="tableScroll" role="region" aria-label={`Prices for recommendations dated ${cohort.date}`} tabIndex={0}>
            <table className="priceTimeline"><caption className="srOnly">Recommendation and subsequent closing prices for {cohort.date}</caption><thead><tr><th scope="col">Stock</th><th scope="col">At recommendation</th><th scope="col">After 5 days</th><th scope="col">After 10 days</th><th scope="col">After 20 days</th><th scope="col">Latest daily close</th><th scope="col">Change since recommendation</th></tr></thead><tbody>
              {cohort.stocks.map(({ticker, main}) => <tr key={ticker}>
                <th scope="row" className="timelineStock"><span className="weeklyRank">#{main.rank ?? "—"}</span> <Link href={`/company/${encodeURIComponent(ticker)}`} className="ticker">{ticker}</Link><small>{main.companies?.name}</small>{main.model_diagnostics?.upcoming_earnings&&<small className="pricePending">Expected earnings {main.model_diagnostics.upcoming_earnings.reported_date} · {main.model_diagnostics.upcoming_earnings.event_time??"time unknown"}</small>}</th>
                <td><PriceCell price={main.recommendation_price} date={main.recommendation_price_date ?? cohort.date}/></td>
                {[5, 10, 20].map(horizon => <td key={horizon}><WindowCell window={main.price_windows?.[String(horizon)]} elapsed={main.trading_days_elapsed} horizon={horizon}/></td>)}
                <td className="latestPriceCell"><PriceCell price={main.current_price} date={main.current_price_date}/></td>
                <td className={main.change_since_recommendation == null ? "" : main.change_since_recommendation >= 0 ? "positive" : "negative"}>{pct(main.change_since_recommendation)}</td>
              </tr>)}
            </tbody></table>
          </div>
          <details className="researchDetails"><summary>Research, selection weights and model evaluation</summary>
          <p className="muted">Original selection evidence is frozen for this group. Evaluation results follow its original entry policy.</p>
        <div className="weeklyCards">{cohort.stocks.map(({ticker, main, horizons}) => {
          const drawdown = main.model_diagnostics?.selection_context?.drawdown_60d;
          const repeat = previousTickers.has(ticker);
          const calibrated = main.model_diagnostics?.ranking_mode === "calibrated_blend";
          const ranker = main.model_diagnostics?.weekly_ranker;
          const financial = main.model_diagnostics?.financial_ranking;
          const delayed = main.model_diagnostics?.entry_policy === "next_session_close";
          return <article className="weeklyStock" key={ticker}>
            <div className="weeklyStockHead"><span className="weeklyRank">#{main.rank}</span><Link href={`/company/${encodeURIComponent(ticker)}`} className="ticker">{ticker}</Link>{repeat && <small className="repeatTag">Also selected previously</small>}</div>
            <p className="stockName">{main.companies?.name ?? ""}</p>
            <p className="modelStatus">{financial ? "Financial priority · fixed research weights · no validated forecast" : ranker ? "Weekly return ranker passed historical validation" : calibrated ? "Validated 5-day model contributes to rank" : "Historical screen · no validated model forecast"}</p>
            <div className="weeklyEvidence"><b>Why it qualified</b>{financial?<><p>{pct(financial.weights.financial,0)} financial · {pct(financial.weights.technical,0)} price · {financial.weights.analyst!=null&&`${pct(financial.weights.analyst,0)} analysts · `}{pct(financial.weights.earnings,0)} earnings surprise.</p><p>Financial score {financial.score.toFixed(1)} / 100 · {pct(financial.coverage,0)} factor coverage. TTM {financial.period_end}, filed {financial.filed_date}; verified against latest filing.</p><small>Points: financial {financial.contributions.financial.toFixed(1)} + price {financial.contributions.technical.toFixed(1)}{financial.contributions.analyst!=null&&` + analysts ${financial.contributions.analyst.toFixed(1)}`} + earnings {financial.contributions.earnings.toFixed(1)}.{!financial.earnings_available&&" Earnings surprise unavailable: neutral score."}</small>{financial.profile==="financial"&&<small>Financial-sector profile: growth, net profitability and earnings valuation. Bank solvency and capital ratios are not covered.</small>}<details><summary>Financial factors and sector comparisons</summary><table><thead><tr><th>Factor</th><th>Value</th><th>Sector score</th></tr></thead><tbody>{Object.entries(financial.factors).map(([key,value])=><tr key={key}><td>{factorNames[key]||key}</td><td>{value.value==null?"—":key==="cash_conversion"||key==="net_debt_to_fcf"?`${value.value.toFixed(2)}×`:pct(value.value)}</td><td>{value.score==null?"Unavailable":value.score.toFixed(1)}</td></tr>)}</tbody></table></details></>:ranker ? <p>5-day expected return vs SPY: {pct(ranker.expected_excess_5d)} · available model inputs: {pct(ranker.feature_coverage, 0)}.</p> : <p>{main.sample_size ?? "—"} similar past setups · {pct(main.historical_up_rate)} rose over 5 trading days · median {pct(main.historical_median_return)}.</p>}{main.catalyst?.reported_date && <small>Recent earnings reported {main.catalyst.reported_date}{main.catalyst.surprise_percent == null ? "" : ` · EPS surprise ${pct(main.catalyst.surprise_percent / 100)}`}</small>}</div>
            {main.model_diagnostics?.analyst_consensus&&<AnalystConsensus data={main.model_diagnostics.analyst_consensus}/>}
            {ranker && <div className="weeklyEvidence risk"><b>Estimated downside</b><p>5-day lower 10th-percentile return: {pct(ranker.downside_p10_5d)}. Losses can exceed this estimate; it is not a loss limit.</p></div>}
            <div className="weeklyEvidence risk"><b>Risk to check</b><p>{drawdown != null && Number(drawdown) <= -0.1 ? `The signal close was ${pct(Math.abs(Number(drawdown)))} below its 60-day high. A rebound is uncertain.` : (main.sample_size ?? 0) < 100 ? "The historical match has fewer than 100 examples. Its observed win rate may be unstable." : "Similar past setups do not guarantee this stock will rise. Review company news and downside before acting."}</p></div>
            {delayed && <p className="muted">Selection close {money(main.model_diagnostics?.selection_close)} · {cohort.date}. Evaluation enters at the next session close and holds for 5/10/20 trading days. Outcomes deduct a 0.2% cost assumption.</p>}
            <div className="priceCompare"><div><small>{delayed ? `Evaluation entry · ${main.model_diagnostics?.execution_entry_date ?? "pending next close"}` : `Selection close · ${cohort.date}`}</small><b>{money(main.entry_price)}</b></div><span>→</span><div><small>Latest close · {main.current_price_date ?? "—"}</small><b>{money(main.current_price)}</b></div></div>
            <div className="weeklyMeta"><span>{ranker ? "Ranking score (basis points)" : "Research rank score"} {main.research_score == null ? "—" : Number(main.research_score).toFixed(1)}</span><span className={main.return_since_signal == null ? "" : main.return_since_signal >= 0 ? "positive" : "negative"}>{delayed ? "Since entry (gross)" : "Since selection"} {pct(main.return_since_signal)}</span></div>
            <div className="horizonGrid">{horizons.map(horizon => <div key={horizon.id} className={`horizon ${horizon.actual_return == null ? "pending" : "done"}`}><b>{horizon.horizon_days} days</b><span>{horizon.model_probability_up == null ? "No validated P↑" : `Model P↑ ${pct(horizon.model_probability_up)}`}</span>{horizon.model_expected_return != null && <small>Model expected {pct(horizon.model_expected_return)}</small>}<small>{horizon.actual_return == null ? "Outcome pending" : `Observed ${pct(horizon.actual_return)}`}</small>{horizon.exit_date && <small>Exit {money(horizon.exit_price)} · {horizon.exit_date}</small>}{horizon.excess_return != null && <small>{pct(horizon.excess_return)} vs SPY</small>}</div>)}</div>
          </article>;
        })}</div>
          </details>
        </div>
      </Cohort>;
    }) : <p className="muted">No weekly decision has been published yet.</p>}
    <details className="researchDetails"><summary>Historical performance and evaluation methodology</summary>
    <div className="scoreGrid">{[5, 10, 20].map(horizon => {
      const score = scorecard.by_horizon?.[String(horizon)];
      return <article key={horizon}><span>{horizon} trading days · observed results</span><strong>{score?.evaluated ? pct(score.win_rate) : "Pending"}</strong><small>{score?.evaluated ? `${score.evaluated} evaluated · ${pct(score.avg_excess_return)} average vs SPY` : "Waiting for matured signals"}</small></article>;
    })}</div>
    <p className="muted">A historical replay (2024–September 2026) trailed SPY over 5, 10 and 20 trading days. It uses current index members and backfilled earnings, so it is descriptive research rather than a validated forecast. <a href="https://github.com/Ronavra/stocksAnalyzer/actions/runs/36480208583">Review the replay</a>.</p>
    <p className="muted">A stock may appear again in a later week. Historical setup rates are descriptive and are not model probabilities. Older cohorts retain their original close-to-close evaluation; new cohorts use next-session entry and costs.</p>
    </details>
  </section>;
}
