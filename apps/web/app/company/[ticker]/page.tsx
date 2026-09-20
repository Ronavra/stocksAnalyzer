import Link from "next/link"; import {getCompany} from "@/lib/api";
const val=(v:any)=>v==null?"—":typeof v==="number"?Number(v).toFixed(1):String(v); const ratio=(v:any)=>v==null?"—":Number(v).toFixed(2); const pct=(v:any)=>v==null?"—":`${(Number(v)*100).toFixed(1)}%`;
export default async function CompanyPage({params}:{params:{ticker:string}}){
 const data=await getCompany(params.ticker); const company=data?.company; const s=data?.snapshots?.[0]; const a=data?.analyst_assessment;
 if(!company)return <main><Link href="/">← Dashboard</Link><h1>Company not found</h1></main>;
 const metrics={"Opportunity score":s?.opportunity_score,"Historical up rate":pct(s?.setup_probability_up),"Median 5d":pct(s?.setup_median_return_5d),"To 60d high":pct(s?.upside_to_60d_high),"60d drawdown":pct(s?.setup_drawdown_60d),"Similar samples":s?.setup_sample_size==null?"—":String(Math.round(Number(s.setup_sample_size)))};
 return <main><Link href="/">← Dashboard</Link><header className="companyHeader"><div><p className="eyebrow">{company.sector||"S&P 500"}</p><h1>{company.ticker} <span className="muted">{company.name}</span></h1><p className="muted">{s?.opportunity_reason||"Latest stored research snapshot"}</p></div></header>
 <section className="scoreGrid">{Object.entries(metrics).map(([k,v])=><article key={k}><span>{k}</span><strong>{val(v)}</strong></article>)}</section>
 <section className="twoCol"><article className="panel"><p className="eyebrow">RESEARCH FACTORS</p><h2>Available scores</h2><p>Fundamentals: <b>{val(s?.fundamentals_score)}</b></p><p>Valuation: <b>{val(s?.valuation_score)}</b></p><p>Earnings: <b>{val(s?.earnings_score)}</b></p><p>P/E: <b>{ratio(s?.pe)}</b></p><p>Price / FCF: <b>{ratio(s?.price_to_fcf)}</b></p></article>
 <article className="panel"><p className="eyebrow">INTERPRETATION</p><h2>What these metrics are</h2><p className="muted">The setup statistics summarize historical price patterns similar to the current setup. They are descriptive research metrics, not a calibrated probability forecast or investment recommendation.</p></article></section>
 <section className="panel"><p className="eyebrow">ANALYST ASSESSMENT</p><h2>Evidence-based view</h2>
 <div className="scoreGrid">
  <article><span>Research score</span><strong>{val(a?.research_score)}</strong></article>
  <article><span>Probability up</span><strong>{a?.probability_up==null?"Not yet modeled":pct(a.probability_up)}</strong></article>
  <article><span>Expected return</span><strong>{a?.expected_return==null?"Not yet modeled":pct(a.expected_return)}</strong></article>
  <article><span>Fair value</span><strong>{a?.fair_value_base==null?"Not yet modeled":val(a.fair_value_base)}</strong></article>
  <article><span>Confidence</span><strong>{val(a?.confidence)}</strong></article>
  <article><span>Thesis status</span><strong>{val(a?.thesis_status)}</strong></article>
 </div>
 <p className="muted">Unavailable forecasts remain explicitly unmodeled until validated out-of-sample evidence and sufficient point-in-time coverage exist.</p>
 {a?.thesis?.length?<><h3>Evidence</h3><ul>{a.thesis.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></>:null}
 {a?.risks?.length?<><h3>Risks</h3><ul>{a.risks.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></>:null}
 {a?.invalidation_conditions?.length?<><h3>Reassess if</h3><ul>{a.invalidation_conditions.map((x:string,i:number)=><li key={i}>{x}</li>)}</ul></>:null}
 </section>
 <section className="panel"><p className="eyebrow">HISTORY</p><h2>Stored research snapshots</h2><p className="muted">{data?.snapshots?.length||0} snapshots available · latest {s?.as_of_date||"—"}</p></section></main>;
}