import Link from "next/link";
import {getCompany} from "@/lib/api";

const val=(v:any)=>v==null?"—":typeof v==="number"?Number(v).toFixed(1):String(v);
const ratio=(v:any)=>v==null?"—":Number(v).toFixed(2);
const pct=(v:any)=>v==null?"—":`${(Number(v)*100).toFixed(1)}%`;
const money=(v:any)=>{if(v==null)return "—";const n=Number(v);return n>=1e9?`$${(n/1e9).toFixed(1)}B`:n>=1e6?`$${(n/1e6).toFixed(1)}M`:`$${n.toLocaleString()}`};

export default async function CompanyPage({params}:{params:{ticker:string}}){
 const data=await getCompany(params.ticker); const company=data?.company; const s=data?.snapshots?.[0]; const a=data?.analyst_assessment;
 if(!company)return <main><Link href="/">← Dashboard</Link><h1>Company not found</h1></main>;
 const metrics={"Opportunity score":s?.opportunity_score,"Historical up rate":pct(s?.setup_probability_up),"Median 5d":pct(s?.setup_median_return_5d),"To 60d high":pct(s?.upside_to_60d_high),"60d drawdown":pct(s?.setup_drawdown_60d),"Similar samples":s?.setup_sample_size==null?"—":String(Math.round(Number(s.setup_sample_size)))};
 const fs=a?.fundamentals; const financials=(data?.financials||[]).filter((x:any)=>x.revenue!=null).slice(0,5);
 return <main><Link href="/">← Dashboard</Link>
 <header className="companyHeader"><div><p className="eyebrow">{company.sector||"S&P 500"}</p><h1>{company.ticker} <span className="muted">{company.name}</span></h1><p className="muted">{s?.opportunity_reason||"Latest stored research snapshot"}</p></div></header>

 <section className="panel researchSummary"><p className="eyebrow">RESEARCH SUMMARY</p><h2>What matters now</h2>
 <div className="scoreGrid">
  <article><span>Research score</span><strong>{val(a?.research_score)}</strong></article>
  <article><span>Confidence</span><strong>{val(a?.confidence)}</strong></article>
  <article><span>Thesis status</span><strong>{val(a?.thesis_status)}</strong></article>
 </div>
 <p className="muted">This page separates observed evidence from forecasts. Probability, expected return and fair value stay unavailable until their models are validated.</p></section>

 <section className="scoreGrid">{Object.entries(metrics).map(([k,v])=><article key={k}><span>{k}</span><strong>{val(v)}</strong></article>)}</section>

 <section className="twoCol">
  <article className="panel"><p className="eyebrow">FUNDAMENTALS</p><h2>Latest annual evidence</h2>
   <div className="metricRows">
    <p><span>Period</span><b>{fs?.period_end||"—"}</b></p>
    <p><span>Revenue growth</span><b>{pct(fs?.revenue_growth)}</b></p>
    <p><span>Operating margin</span><b>{pct(fs?.operating_margin)}</b></p>
    <p><span>FCF margin</span><b>{pct(fs?.fcf_margin)}</b></p>
    <p><span>Net debt / FCF</span><b>{fs?.net_debt_to_fcf==null?"—":`${Number(fs.net_debt_to_fcf).toFixed(1)}x`}</b></p>
   </div><small>Source: {fs?.source?.toUpperCase()||"Not available"}</small>
  </article>
  <article className="panel"><p className="eyebrow">MODEL STATUS</p><h2>Forecast readiness</h2>
   <div className="metricRows"><p><span>Probability up</span><b>{a?.probability_up==null?"Not yet modeled":pct(a.probability_up)}</b></p><p><span>Expected return</span><b>{a?.expected_return==null?"Not yet modeled":pct(a.expected_return)}</b></p><p><span>Fair value</span><b>{a?.fair_value_base==null?"Not yet modeled":val(a.fair_value_base)}</b></p><p><span>Evidence coverage</span><b>{a?.evidence_coverage==null?"—":`${Number(a.evidence_coverage).toFixed(0)}%`}</b></p></div>
  </article>
 </section>

 {financials.length?<section className="panel"><p className="eyebrow">FINANCIAL TREND</p><h2>Annual fundamentals</h2><div className="tableScroll"><table className="financialTable"><thead><tr><th>Fiscal year</th><th>Revenue</th><th>Operating income</th><th>Net income</th><th>Free cash flow</th><th>Cash</th><th>Debt</th></tr></thead><tbody>{financials.map((x:any)=><tr key={x.period_end}><td>{x.period_end}</td><td>{money(x.revenue)}</td><td>{money(x.operating_income)}</td><td>{money(x.net_income)}</td><td>{money(x.free_cash_flow)}</td><td>{money(x.cash)}</td><td>{money(x.total_debt)}</td></tr>)}</tbody></table></div></section>:null}

 <section className="panel"><p className="eyebrow">ANALYST ASSESSMENT</p><h2>Evidence-based view</h2>
 {a?.catalyst?<div className="catalystBanner"><b>Latest earnings · {a.catalyst.reported_date||"—"}</b><span>EPS surprise {a.catalyst.eps_surprise_pct==null?"—":`${Number(a.catalyst.eps_surprise_pct).toFixed(1)}%`} · Revenue surprise {a.catalyst.revenue_surprise_pct==null?"—":`${Number(a.catalyst.revenue_surprise_pct).toFixed(1)}%`}</span></div>:null}
 <div className="assessmentCols">
  <div>{a?.thesis?.length?<><h3>Evidence</h3><ul>{a.thesis.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></>:<p className="muted">No evidence available.</p>}</div>
  <div>{a?.risks?.length?<><h3>Risks</h3><ul>{a.risks.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></>:null}</div>
 </div>
 {a?.invalidation_conditions?.length?<><h3>Reassess if</h3><ul>{a.invalidation_conditions.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></>:null}
 </section>
 <section className="panel"><p className="eyebrow">HISTORY</p><h2>Stored research snapshots</h2><p className="muted">{data?.snapshots?.length||0} snapshots available · latest {s?.as_of_date||"—"}</p></section>
 </main>;
}