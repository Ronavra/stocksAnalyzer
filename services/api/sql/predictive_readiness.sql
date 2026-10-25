-- A read-only compact view of collection quality and independent model research.
create or replace function public.research_predictive_readiness()
returns jsonb language sql stable security invoker set search_path='' as $$
with estimates as materialized (
 select e.* from public.estimate_snapshots e join public.companies c on c.id=e.company_id and c.is_sp500
 where e.captured_at between now()-interval '48 hours' and now()
), financial as (
 select finished_at,metadata->'financial_audit' audit from public.pipeline_runs
 where pipeline='research_sources_refresh' and metadata->'financial_audit'->>'scope'='full_universe'
 order by started_at desc,id desc limit 1
), source_runs as (
 select distinct on(pipeline) pipeline,status,started_at,finished_at,error_message,
 metadata->'coverage_status' coverage_status,metadata->'errors' errors,metadata->'warnings' warnings
 from public.pipeline_runs where pipeline in ('macro_sources_refresh','official_documents_refresh',
 'corporate_actions_refresh','source_coverage_audit','estimate_consensus_refresh','financial_coverage_repair')
 order by pipeline,started_at desc,id desc
)
select jsonb_build_object(
 'history',public.research_model_readiness(),
 'quality',jsonb_build_object(
  'estimate_companies',(select count(distinct company_id) from estimates),
  'eps_basis_verified_companies',(select count(distinct company_id) from estimates where eps_consensus is not null and eps_basis in ('gaap','adjusted','non-gaap')),
  'eps_basis_unknown_companies',(select count(distinct company_id) from estimates where eps_consensus is not null and eps_basis='unknown'),
  'eps_currency_known_companies',(select count(distinct company_id) from estimates where eps_consensus is not null and eps_currency is not null),
  'inconsistent_estimate_companies',(select count(distinct company_id) from estimates where eps_consensus<eps_low or eps_consensus>eps_high or revenue_consensus<revenue_low or revenue_consensus>revenue_high),
  'financial_checked_at',(select finished_at from financial),
  'financial_summary',(select audit->'summary' from financial),
  'guidance_companies_90d',(select count(distinct company_id) from public.corporate_guidance_events where event_date>=current_date-90),
  'guidance_matched_events',(select count(*) from public.guidance_consensus_matches),
  'fresh_macro_series',(select count(*) from (select distinct on(source) source,status,checked_at from public.research_collection_checks where family='macro' and company_id is null
     and source in ('DFF','DGS2','DGS10','CPIAUCSL','UNRATE','PAYEMS','GDPC1','DTWEXBGS','DCOILWTICO') order by source,checked_at desc,id desc)c where c.status='success' and c.checked_at>=now()-interval '48 hours')
 ),
 'latest_twenty_day_validation',(select jsonb_build_object('id',id,'status',case when status='running' and started_at<now()-interval '6 hours' then 'interrupted' else status end,
   'started_at',started_at,'finished_at',finished_at,'results',results,'error_message',error_message)
   from public.model_validation_runs where model_version='twenty-session-excess-v1' order by started_at desc,id desc limit 1),
 'source_runs',coalesce((select jsonb_agg(to_jsonb(r) order by r.pipeline) from source_runs r),'[]'::jsonb),
 'requirements',jsonb_build_object('primary_horizon_days',20,'max_positions',10,'minimum_mature_dates',180,
 'minimum_training_rows',5000,'minimum_training_dates',52,'minimum_selection_dates',26,'minimum_holdout_dates',26,
 'sample_stride_sessions',5,'family_minimum_observed_training_dates',26),
 'active_selection_changed',false,'validated_forecast',false
);
$$;
revoke all on function public.research_predictive_readiness() from public,anon,authenticated;
grant execute on function public.research_predictive_readiness() to service_role;

create or replace function public.reconcile_predictive_research_leases()
returns jsonb language plpgsql security invoker set search_path='' as $$
declare models int; local_runs int;
begin
 perform pg_catalog.pg_advisory_xact_lock(73519248);
 update public.model_validation_runs set status='error',finished_at=now(),
 error_message='Research worker exceeded six-hour lease; no forecast promotion.'
 where status='running' and started_at<now()-interval '6 hours';
 get diagnostics models=row_count;
 update public.pipeline_runs set status='error',finished_at=now(),error_message='Local research worker exceeded six-hour lease; retry on the archive computer.'
 where pipeline='local_model_validation' and status='running' and started_at<now()-interval '6 hours';
 get diagnostics local_runs=row_count;
 return jsonb_build_object('expired_model_runs',models,'expired_local_runs',local_runs);
end $$;
revoke all on function public.reconcile_predictive_research_leases() from public,anon,authenticated;
grant execute on function public.reconcile_predictive_research_leases() to service_role;
