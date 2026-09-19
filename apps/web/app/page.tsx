import Link from "next/link";
import {getCandidates} from "@/lib/api";
export default async function Home(){
 const candidates=await getCandidates();
 return <main><header><div><p className="eyebrow">S&P 500 RESEARCH DESK</p><h1>StocksAnalyzer</h1><p className="sub">Evidence-first weekly equity research.</p></div><span className="badge">MVP · v0.2</span></header>
 <section className="grid"><article><span>Target universe</span><strong>S&P 500</strong><small>live universe integration next</small></article><article><span>Research queue</span><strong>{candidates.length||"—"}</strong><small>API-ranked demo candidates</small></article><article><span>Method</span><strong>6 factors</strong><small>fundamentals · valuation · earnings · momentum · news · catalysts</small></article></section>
 <section className="panel"><div className="panelHead"><div><p className="eyebrow">WEEKLY SCREEN</p><h2>Research candidates</h2></div><p className="muted">Demo inputs until live providers are connected</p></div>
 {candidates.length?<table><thead><tr><th>Ticker</th><th>Company</th><th>Sector</th><th>Signal</th><th>Score</th><th>Key catalyst</th></tr></thead><tbody>{candidates.map(x=><tr key={x.ticker}><td><Link className="ticker" href={`/company/${x.ticker}`}>{x.ticker}</Link></td><td>{x.company}</td><td>{x.sector}</td><td>{x.signal}</td><td>{x.score}</td><td>{x.catalyst}</td></tr>)}</tbody></table>:<p className="muted">Backend unavailable. Start FastAPI on port 8000.</p>}</section></main>
}