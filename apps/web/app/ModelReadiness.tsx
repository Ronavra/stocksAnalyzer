type Training={status:string;started_at?:string;finished_at?:string;error_message?:string|null;model_version?:string};
type Readiness={history_requires_local_archive:boolean;archive_verified_at?:string;
 financial_observation_days:number;estimate_observation_days:number;fiscal_estimate_companies:number;
 minimum_observed_sample_dates:number;latest_execution?:{metadata?:{outcome?:string;reason?:string}};latest_training?:Training};

export default function ModelReadiness({data}:{data?:Readiness|null}){
 if(!data)return null;
 const outcome=data.latest_execution?.metadata?.outcome;
 const deferred=outcome==="deferred_archive_required";
 const interrupted=data.latest_training?.status==="interrupted";
 return <section className="panel"><p className="eyebrow">MODEL READINESS</p>
  <h2>{deferred?"Training awaits the local archive":interrupted?"Previous validation was interrupted":"Research history and validation"}</h2>
  <p className="muted">The current selection uses one fixed 45/35/10/10 policy. Data collection and successful software checks do not establish predictive accuracy.</p>
  <div className="definitions">
   <div><b>Fiscal EPS and revenue estimates</b><span>{data.fiscal_estimate_companies} companies with recent observations</span></div>
   <div><b>Financial observation history</b><span>{data.financial_observation_days} captured dates</span></div>
   <div><b>Estimate observation history</b><span>{data.estimate_observation_days} captured dates</span></div>
   <div><b>Validation execution</b><span>{deferred?"Deferred · hosted runner cannot access the full archive":outcome?.replaceAll("_"," ")??"No recent execution report"}</span></div>
   <div><b>Last training record</b><span>{data.latest_training?.status??"Not run"} · {data.latest_training?.finished_at??data.latest_training?.started_at??"No timestamp"}</span></div>
  </div>
  <p className="muted">New evidence families need at least {data.minimum_observed_sample_dates} sampled dates, including sufficient dates before the later evaluation period. Captured dates alone do not meet that requirement. Training also checks sample size and performance on unseen dates.</p>
  {data.history_requires_local_archive&&<p className="muted">Full-history research must run on the computer holding the verified market archive. Its weekly task runs after Friday&apos;s close and catches up through the local daily scheduler. Training status and any forecast promotion are recorded separately.</p>}
  {data.latest_training?.error_message&&<p className="muted">Last validation: {data.latest_training.error_message}</p>}
 </section>;
}
