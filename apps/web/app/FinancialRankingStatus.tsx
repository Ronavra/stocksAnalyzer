type Comparison = {
  status?: string;
  finished_at?: string;
  metadata?: {policy_version?:string;all?: {cohorts?: number; mean_net_return?: number; mean_improvement_vs_baseline?: number; weeks_in_cash?: number}};
};
const pct = (value?: number) => value == null ? "—" : `${(value * 100).toFixed(2)}%`;

export default function FinancialRankingStatus({comparison}: {comparison?: Comparison | null}) {
  const metrics = comparison?.metadata?.policy_version==="financial-analyst-priority-v2"?comparison?.metadata?.all:null;
  return <section className="panel" aria-label="Financial selection policy">
    <div className="panelHead"><div><p className="eyebrow">ACTIVE WEEKLY SELECTION POLICY</p><h2>45% financial · 35% price · 10% analysts · 10% earnings surprise</h2></div></div>
    <p className="muted">Financial factors are compared within sectors. The latest SEC filing must be verified, the reporting period must be within 180 days and weighted factor coverage must reach 80%. Missing financial factors earn no points; missing recent earnings surprise is neutral. Up to five qualifying companies, with repeats allowed.</p>
    <p className="muted">Analyst consensus needs at least three analysts, collection within seven days and a provider period within 45 days. Missing or stale consensus contributes a neutral score of 50; its 10% is not redistributed. Frozen older cohorts retain their original weights. Analyst price targets are supplementary.</p>
    {metrics && <div className="definitions">
      <div><b>Exploratory replay weeks</b><span>{metrics.cohorts ?? 0}</span></div>
      <div><b>Average after-cost return</b><span>{pct(metrics.mean_net_return)}</span></div>
      <div><b>Average change vs previous screen</b><span>{pct(metrics.mean_improvement_vs_baseline)}</span></div>
      <div><b>Weeks without qualifying picks</b><span>{metrics.weeks_in_cash ?? 0}</span></div>
    </div>}
    <p className="muted">Fixed research weights, not a calibrated prediction. Improved forward performance has not been established. Historical analyst testing requires observations saved at the time; collection starts with this update. {comparison?.metadata?.policy_version!=="financial-analyst-priority-v2"&&comparison?.finished_at&&`The existing replay (${comparison.metadata?.policy_version}) concerns an older policy.`}</p>
  </section>;
}
