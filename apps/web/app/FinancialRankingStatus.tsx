type Comparison = {
  status?: string;
  finished_at?: string;
  metadata?: {all?: {cohorts?: number; mean_net_return?: number; mean_improvement_vs_baseline?: number; weeks_in_cash?: number}};
};
const pct = (value?: number) => value == null ? "—" : `${(value * 100).toFixed(2)}%`;

export default function FinancialRankingStatus({comparison}: {comparison?: Comparison | null}) {
  const metrics = comparison?.metadata?.all;
  return <section className="panel" aria-label="Financial selection policy">
    <div className="panelHead"><div><p className="eyebrow">ACTIVE WEEKLY SELECTION POLICY</p><h2>50% financial · 40% price · 10% earnings surprise</h2></div></div>
    <p className="muted">Financial factors are compared within sectors. The latest SEC filing must be verified, the reporting period must be within 180 days and weighted factor coverage must reach 80%. Missing financial factors earn no points; missing recent earnings surprise is neutral. Up to five qualifying companies, with repeats allowed.</p>
    {metrics && <div className="definitions">
      <div><b>Exploratory replay weeks</b><span>{metrics.cohorts ?? 0}</span></div>
      <div><b>Average after-cost return</b><span>{pct(metrics.mean_net_return)}</span></div>
      <div><b>Average change vs previous screen</b><span>{pct(metrics.mean_improvement_vs_baseline)}</span></div>
      <div><b>Weeks without qualifying picks</b><span>{metrics.weeks_in_cash ?? 0}</span></div>
    </div>}
    <p className="muted">Fixed research weights, not a calibrated prediction. Historical financial backfills and current constituents limit this replay; improved forward performance has not been established. {comparison?.finished_at && `Replay completed ${comparison.finished_at}.`}</p>
  </section>;
}
