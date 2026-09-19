import Link from "next/link";
import {getCompany} from "@/lib/api";

export default async function CompanyPage({params}:{params:{ticker:string}}) {
  const item = await getCompany(params.ticker);
  if (!item) return <main><Link href="/">← Dashboard</Link><h1>Company not found</h1></main>;
  return <main>
    <Link href="/">← Dashboard</Link>
    <header className="companyHeader"><div><p className="eyebrow">{item.sector}</p><h1>{item.ticker} <span className="muted">{item.company}</span></h1><p>{item.catalyst}</p></div><div className="score">{item.score}<small>research score</small></div></header>
    <section className="scoreGrid">{Object.entries(item.scores).map(([k,v])=><article key={k}><span>{k}</span><strong>{v}</strong></article>)}</section>
    <section className="twoCol">
      <article className="panel"><p className="eyebrow">WHAT CHANGED</p><h2>Weekly evidence</h2><p>{item.what_changed}</p></article>
      <article className="panel"><p className="eyebrow">MARKET ASSUMPTION</p><h2>What may be priced in</h2><p>{item.market_assumption}</p></article>
    </section>
    <section className="panel"><p className="eyebrow">NEXT RESEARCH LAYER</p><h2>Evidence pipeline</h2><div className="framework">{["SEC filings","Earnings & guidance","Estimate revisions","Valuation","News","Macro/sector","Sentiment","Bull/Base/Bear"].map(x=><span key={x}>{x}</span>)}</div></section>
  </main>;
}