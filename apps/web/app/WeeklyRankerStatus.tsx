type Metrics = {
  cohorts?: number;
  mean_excess_vs_spy?: number;
  mean_improvement_vs_screen?: number;
  worst_week?: number;
};
type Validation = {
  status?: string;
  finished_at?: string;
  promotion_passed?: boolean;
  error_message?: string;
  holdout?: Metrics;
};
const pct = (value?: number) => value == null ? "—" : `${(value * 100).toFixed(2)}%`;

export default function WeeklyRankerStatus({validation}: {validation?: Validation | null}) {
  const status = !validation ? "Waiting for first validation"
    : validation.status === "running" ? "Historical validation running"
    : validation.status === "error" ? "Validation failed"
    : validation.promotion_passed ? "Historical promotion checks passed"
    : "Validation completed · weekly ranker not promoted";
  return <section className="panel" aria-label="Weekly ranker validation">
    <div className="panelHead"><div><p className="eyebrow">SEPARATE PRICE MODEL EXPERIMENT</p><h2>{status}</h2></div><p className="muted">This experiment is separate from the active 45 / 35 / 10 / 10 financial selection policy.</p></div>
    {validation?.holdout && <div className="definitions">
      <div><b>Final audit weeks</b><span>{validation.holdout.cohorts ?? 0}</span></div>
      <div><b>Average after-cost return vs SPY</b><span>{pct(validation.holdout.mean_excess_vs_spy)}</span></div>
      <div><b>Average improvement vs existing screen</b><span>{pct(validation.holdout.mean_improvement_vs_screen)}</span></div>
      <div><b>Worst after-cost week</b><span>{pct(validation.holdout.worst_week)}</span></div>
    </div>}
    {validation?.finished_at && <p className="muted">Completed {validation.finished_at}. Historical checks do not establish future performance; production also requires a recent validation and current inputs.</p>}
    {validation?.error_message && <p className="muted">{validation.error_message}</p>}
  </section>;
}
