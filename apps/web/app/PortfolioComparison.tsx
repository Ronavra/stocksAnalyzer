"use client";
import {useState} from "react";
import "./portfolio.css";

type Point={date:string;equity:number;benchmark_equity:number;cash:number;trading_costs:number};
type Summary={start_date?:string;as_of_date?:string;cumulative_return?:number;benchmark_return?:number;excess_return?:number;
 max_drawdown?:number;benchmark_max_drawdown?:number;cash_fraction?:number;portfolio_value?:number;benchmark_value?:number;
 trading_costs?:number;funded_cohorts?:number;completed_cohorts?:number;open_cohorts?:number;cash_cohorts?:number;unfunded_cohorts?:number};
type Replay={status:string;summary:Summary;curve:Point[];sleeves?:number;issues:{reason:string;date?:string;company_ids?:number[]}[];pending_cohorts:number};
export type PortfolioData={selection_policy?:{name:string;version:string;weights:Record<string,number>};active_version?:string;initial_capital?:number;by_policy:Record<string,Record<string,Record<string,Record<string,Replay>>>>;
 tickers?:Record<string,string>;market_current?:boolean;expected_market_date?:string;latest_market_date?:string;total_return_source_error?:string|null};
const pct=(n:number|null|undefined)=>n==null?"Pending":`${(n*100).toFixed(2)}%`;
const money=(n:number|undefined)=>n==null?"—":new Intl.NumberFormat("en-US",{style:"currency",currency:"USD",maximumFractionDigits:2}).format(n);

function EquityChart({points,initial}:{points:Point[];initial:number}){
 if(!points.length)return null;
 const width=820,height=280,left=64,right=18,top=18,bottom=35;
 const values=[initial,...points.flatMap(p=>[p.equity,p.benchmark_equity])];
 const min=Math.min(...values),max=Math.max(...values),padding=Math.max((max-min)*.12,initial*.002);
 const low=min-padding,high=max+padding;
 const x=(i:number)=>left+(width-left-right)*i/Math.max(1,points.length-1);
 const y=(n:number)=>top+(height-top-bottom)*(high-n)/(high-low);
 return <figure className="portfolioChart"><svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Portfolio value compared with SPY, both starting with the same capital">
  <title>Portfolio and SPY values in US dollars</title>
  {[low,(low+high)/2,high].map(v=><g key={v}><line x1={left} x2={width-right} y1={y(v)} y2={y(v)} stroke="#273247"/><text x={left-8} y={y(v)+4} textAnchor="end" fill="#8993a3" fontSize="11">{money(v)}</text></g>)}
  <polyline points={points.map((p,i)=>`${x(i)},${y(p.benchmark_equity)}`).join(" ")} fill="none" stroke="#91a6cb" strokeWidth="2"/>
  <polyline points={points.map((p,i)=>`${x(i)},${y(p.equity)}`).join(" ")} fill="none" stroke="#64d2a1" strokeWidth="2.5"/>
  {points.map((p,i)=><circle key={p.date} cx={x(i)} cy={y(p.equity)} r="3" fill="#64d2a1"><title>{`${p.date}: portfolio ${money(p.equity)}; SPY ${money(p.benchmark_equity)}; cash ${money(p.cash)}`}</title></circle>)}
  <text x={left} y={height-8} fill="#8993a3" fontSize="11">{points[0].date}</text>
  <text x={width-right} y={height-8} textAnchor="end" fill="#8993a3" fontSize="11">{points[points.length-1].date}</text>
 </svg><figcaption><span className="portfolioLegend">● Portfolio</span><span className="benchmarkLegend">● SPY buy and hold</span></figcaption></figure>;
}

export default function PortfolioComparison({data}:{data?:PortfolioData}){
 const policy=data?.active_version;
 const weights=data?.selection_policy?.weights??{financial:.45,technical:.35,analyst:.1,earnings:.1};
 const [horizon,setHorizon]=useState("5");
 const [basis,setBasis]=useState("total_return");
 const [scenario,setScenario]=useState("base");
 const current=policy?data?.by_policy[policy]:undefined;
 const row=current?.[horizon]?.[basis]?.[scenario];
 const summary=row?.summary??{};
 return <section className="panel portfolioPanel">
  <div className="panelHead"><div><p className="eyebrow">PORTFOLIO VS S&amp;P 500</p><h2>Are we beating the benchmark?</h2></div><span className="badge">Observed paper portfolio</span></div>
  <p className="muted">One current weekly selection policy: {Math.round(weights.financial*100)}% financial, {Math.round(weights.technical*100)}% price, {Math.round(weights.analyst*100)}% analysts and {Math.round(weights.earnings*100)}% earnings surprise. Each holding period starts with {money(data?.initial_capital??10000)}. SPY is held over the same dates. Positive excess means the portfolio finished ahead; it does not establish a repeatable advantage.</p>
  {!data||!current?<p className="muted">Current-policy portfolio data could not be loaded. Retry the dashboard; older versions are never substituted.</p>:<>
  <div className="portfolioControls">
   <label>Holding period<select value={horizon} onChange={e=>setHorizon(e.target.value)}>{[5,10,20].map(h=><option key={h} value={h}>{h} trading days</option>)}</select></label>
   <label>Return basis<select aria-describedby="return-basis-help" value={basis} onChange={e=>setBasis(e.target.value)}><option value="total_return">Dividends reinvested</option><option value="price_return">Price only · excludes dividends</option></select></label>
   <label>Trading costs<select aria-describedby="trading-costs-help" value={scenario} onChange={e=>setScenario(e.target.value)}><option value="base">Base · 0.20% round trip</option><option value="stress">Stress · 0.50% round trip</option></select></label>
  </div>
  <p id="return-basis-help" className="muted">{basis==="total_return"?"Return basis includes price changes and reinvested dividends for both the portfolio and SPY.":"Return basis measures price changes only; dividends are excluded for both the portfolio and SPY."}</p>
  <p id="trading-costs-help" className="muted">Trading costs are an assumed fee and execution allowance: {scenario==="base"?"0.10% per buy and per sell (about $20 per $10,000 for a completed round trip).":"0.25% per buy and per sell (about $50 per $10,000 for a completed round trip)."} These are simulation assumptions, not your broker&apos;s actual charges. Changing these controls measures the same selections; it does not choose different stocks.</p>
  {data.market_current===false&&<p className="negative" role="status">Market data ends {data.latest_market_date??"unknown"}; expected {data.expected_market_date}. This comparison is not current.</p>}
  {basis==="total_return"&&data.total_return_source_error&&<p className="negative" role="status">{data.total_return_source_error}</p>}
  {row?.status==="blocked"&&<p className="negative" role="status">Comparison incomplete. {row.issues.slice(0,3).map((issue,i)=><span key={i}>{issue.reason.replaceAll("_"," ")}{issue.date?` on ${issue.date}`:""}{issue.company_ids?.length?`: ${issue.company_ids.map(id=>data.tickers?.[String(id)]??id).join(", ")}`:""}. </span>)}{row.curve.length>0?`Values below stop at ${summary.as_of_date}.`:"No return is reported from incomplete data."}</p>}
  {row?.status==="pending"&&<p className="muted">Waiting for a published recommendation and its first executable market close.</p>}
  {!!row?.curve.length&&<>
   <div className="grid portfolioMetrics"><article><span>Portfolio return</span><strong>{pct(summary.cumulative_return)}</strong><small>{money(summary.portfolio_value)}</small></article><article><span>SPY return</span><strong>{pct(summary.benchmark_return)}</strong><small>{money(summary.benchmark_value)}</small></article><article><span>Excess vs SPY</span><strong className={(summary.excess_return??0)<0?"negative":"positive"}>{pct(summary.excess_return)}</strong><small>Difference in percentage points</small></article></div>
   <EquityChart points={row.curve} initial={data.initial_capital??10000}/>
   <div className="definitions"><div><b>Maximum drawdown</b><span>Portfolio {pct(summary.max_drawdown)} · SPY {pct(summary.benchmark_max_drawdown)}</span></div><div><b>Trading costs incurred</b><span>{money(summary.trading_costs)} · cash {pct(summary.cash_fraction)}</span></div><div><b>Recommendation groups</b><span>{summary.funded_cohorts??0} funded · {summary.completed_cohorts??0} closed · {summary.open_cohorts??0} still open</span></div><div><b>Capital availability</b><span>{row.sleeves} funded sleeves · {summary.unfunded_cohorts??0} groups skipped because capital was committed · {summary.cash_cohorts??0} no-pick groups</span></div></div>
   <p className="muted">{summary.start_date}–{summary.as_of_date}. {basis==="total_return"?"Includes provider-adjusted dividends reinvested.":"Excludes dividends on both sides."} Entry occurs at the first market close after both the signal date and actual publication. Costs are charged on each buy and sell; SPY pays its entry cost. Open holdings are valued at the latest available close.</p>
  </>}
  <details className="researchDetails"><summary>Portfolio rules and daily values</summary><p className="muted">Capital is split into {Math.ceil(Number(horizon)/5)} sleeves, with equal weights within each recommendation group. Exits release capital before new entries. Idle capital earns zero; there is no borrowing. Taxes, spread variations and guaranteed fills are not modeled. Annualized returns are withheld until a full year has elapsed. Earlier code versions remain in recommendation history and are excluded from this current-policy comparison.</p>
   {row?.curve.length?<div className="tableScroll"><table><thead><tr><th>Date</th><th>Portfolio</th><th>SPY</th><th>Cash</th><th>Costs to date</th></tr></thead><tbody>{row.curve.map(p=><tr key={p.date}><td>{p.date}</td><td>{money(p.equity)}</td><td>{money(p.benchmark_equity)}</td><td>{money(p.cash)}</td><td>{money(p.trading_costs)}</td></tr>)}</tbody></table></div>:null}
  </details>
  </>}
 </section>;
}
