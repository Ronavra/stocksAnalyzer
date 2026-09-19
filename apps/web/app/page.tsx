const candidates = [
  {ticker:"NVDA",company:"NVIDIA",signal:"Research",score:82,catalyst:"AI demand / estimates"},
  {ticker:"MSFT",company:"Microsoft",signal:"Research",score:79,catalyst:"Cloud + AI monetization"},
  {ticker:"AMZN",company:"Amazon",signal:"Research",score:77,catalyst:"AWS / margins"},
  {ticker:"AVGO",company:"Broadcom",signal:"Research",score:76,catalyst:"AI networking"},
];

export default function Home() {
  return <main>
    <header><div><p className="eyebrow">S&P 500 RESEARCH DESK</p><h1>StocksAnalyzer</h1><p className="sub">Evidence-first weekly equity research.</p></div><span className="badge">MVP</span></header>
    <section className="grid">
      <article><span>Universe</span><strong>503</strong><small>S&P 500 securities</small></article>
      <article><span>Research queue</span><strong>{candidates.length}</strong><small>initial demo candidates</small></article>
      <article><span>Next layer</span><strong>Live data</strong><small>fundamentals · news · earnings</small></article>
    </section>
    <section className="panel"><div className="panelHead"><div><p className="eyebrow">WEEKLY SCREEN</p><h2>Research candidates</h2></div><p className="muted">Demo scores — not investment recommendations</p></div>
      <table><thead><tr><th>Ticker</th><th>Company</th><th>Signal</th><th>Research score</th><th>Key catalyst</th></tr></thead>
      <tbody>{candidates.map(x=><tr key={x.ticker}><td className="ticker">{x.ticker}</td><td>{x.company}</td><td>{x.signal}</td><td>{x.score}</td><td>{x.catalyst}</td></tr>)}</tbody></table>
    </section>
    <section className="panel"><p className="eyebrow">RESEARCH FRAMEWORK</p><h2>What changed → why it matters</h2>
      <div className="framework">{["What happened","Why investors care","Short vs long term","Financial metric affected","Market assumptions","Bull / Base / Bear","Catalysts & risks","Thesis change"].map(x=><span key={x}>{x}</span>)}</div>
    </section>
  </main>;
}