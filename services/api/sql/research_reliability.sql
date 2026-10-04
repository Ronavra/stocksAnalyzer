-- Atomic publication, including explicit no-pick weeks. Service-role access only.
create table if not exists public.recommendation_cohorts (
 signal_date date primary key,
 model_version text not null,
 horizons integer[] not null,
 expected_picks integer not null check (expected_picks between 0 and 5),
 status text not null check (status in ('published','no_picks')),
 published_at timestamptz not null default now(),
 metadata jsonb not null default '{}'::jsonb
);
alter table public.recommendation_cohorts enable row level security;
revoke all on public.recommendation_cohorts from public, anon, authenticated;
grant select, insert on public.recommendation_cohorts to service_role;

-- Register complete legacy cohorts without changing any frozen prediction.
insert into public.recommendation_cohorts(signal_date,model_version,horizons,expected_picks,published_at,status,metadata)
select signal_date,min(model_version),array_agg(distinct horizon_days order by horizon_days),
 count(distinct company_id),min(created_at),'published',jsonb_build_object('legacy_import',true)
from public.research_predictions
group by signal_date
having count(distinct model_version)=1 and count(distinct company_id)<=5
 and count(*)=count(distinct company_id)*count(distinct horizon_days)
on conflict(signal_date) do nothing;

create or replace function public.publish_recommendation_cohort(
 p_signal_date date, p_model_version text, p_horizons integer[],
 p_predictions jsonb, p_metadata jsonb
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare n integer; picks integer; existing public.recommendation_cohorts;
begin
 perform pg_advisory_xact_lock(hashtextextended('weekly-cohort:'||p_signal_date::text,0));
 select * into existing from public.recommendation_cohorts where signal_date=p_signal_date;
 if found then
  return jsonb_build_object('status','already_published','expected_picks',existing.expected_picks);
 end if;
 if p_model_version is null or p_signal_date is null or cardinality(p_horizons)=0
  or p_horizons is null or not (p_horizons <@ array[5,10,20])
  or cardinality(p_horizons)<>(select count(distinct h) from unnest(p_horizons) h)
  or jsonb_typeof(p_predictions) is distinct from 'array' then
  raise exception 'Invalid cohort contract';
 end if;
 select count(*),count(distinct company_id) into n,picks
 from jsonb_populate_recordset(null::public.research_predictions,p_predictions);
 if picks>5 or n<>picks*cardinality(p_horizons)
  or exists(select 1 from jsonb_populate_recordset(null::public.research_predictions,p_predictions) r
   where r.company_id is null or r.signal_date is distinct from p_signal_date
    or r.model_version is distinct from p_model_version or r.signal is distinct from 'UP'
    or r.horizon_days is null or not(r.horizon_days=any(p_horizons))
    or r.rank is null or r.rank<1 or r.rank>picks
    or r.evaluated_at is not null or r.actual_return is not null or r.entry_price is not null)
  or n<>(select count(distinct (company_id,horizon_days))
    from jsonb_populate_recordset(null::public.research_predictions,p_predictions))
  or picks<>(select count(distinct rank) from jsonb_populate_recordset(null::public.research_predictions,p_predictions))
  or exists(select 1 from jsonb_populate_recordset(null::public.research_predictions,p_predictions)
    group by company_id having count(distinct rank)<>1) then
  raise exception 'Incomplete or inconsistent cohort';
 end if;
 -- A legacy incomplete, unevaluated publication may be retried atomically.
 -- Evaluated or differently versioned evidence must never be replaced.
 if exists(select 1 from public.research_predictions where signal_date=p_signal_date
    and (evaluated_at is not null or model_version<>p_model_version)) then
  raise exception 'Legacy cohort requires explicit recovery; preserving evidence';
 end if;
 delete from public.research_predictions where signal_date=p_signal_date;
 insert into public.research_predictions(company_id,signal_date,horizon_days,signal,rank,
  research_score,historical_up_rate,historical_median_return,sample_size,catalyst,model_version,
  model_probability_up,model_expected_return,model_calibration_brier,model_baseline_brier,
  model_feature_coverage,model_diagnostics)
 select company_id,signal_date,horizon_days,signal,rank,research_score,historical_up_rate,
  historical_median_return,sample_size,catalyst,model_version,model_probability_up,
  model_expected_return,model_calibration_brier,model_baseline_brier,model_feature_coverage,model_diagnostics
 from jsonb_populate_recordset(null::public.research_predictions,p_predictions);
 insert into public.recommendation_cohorts(signal_date,model_version,horizons,expected_picks,status,metadata)
 values(p_signal_date,p_model_version,p_horizons,picks,case when picks=0 then 'no_picks' else 'published' end,p_metadata);
 insert into public.pipeline_runs(pipeline,status,started_at,finished_at,metadata)
 values('weekly_financial_selection','success',now(),now(),p_metadata);
 return jsonb_build_object('status','published','expected_picks',picks,'rows',n);
end $$;
revoke all on function public.publish_recommendation_cohort(date,text,integer[],jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.publish_recommendation_cohort(date,text,integer[],jsonb,jsonb) to service_role;

-- Append-only observations preserve revised financial statements from now on.
-- Baseline rows are observed NOW; they do not claim historic availability.
create table if not exists public.financial_metric_versions (
 id bigint generated always as identity primary key,
 company_id bigint not null references public.companies(id),
 period_end date not null,
 period_type text not null,
 fingerprint text not null,
 observed_at timestamptz not null default now(),
 provenance text not null,
 snapshot jsonb not null,
 unique(company_id,period_end,period_type,fingerprint)
);
create index if not exists financial_metric_versions_asof_idx on public.financial_metric_versions(company_id,observed_at);
alter table public.financial_metric_versions enable row level security;
revoke all on public.financial_metric_versions from public,anon,authenticated;
grant select,insert on public.financial_metric_versions to service_role;
grant usage,select on sequence public.financial_metric_versions_id_seq to service_role;
create or replace function public.capture_financial_metric_version()
returns trigger language plpgsql security invoker set search_path='' as $$
declare payload jsonb;
begin
 payload=to_jsonb(new)-'id'-'captured_at';
 insert into public.financial_metric_versions(company_id,period_end,period_type,fingerprint,provenance,snapshot)
 values(new.company_id,new.period_end,new.period_type,md5(payload::text),'live_ingestion',to_jsonb(new))
 on conflict(company_id,period_end,period_type,fingerprint) do nothing;
 return new;
end $$;
revoke all on function public.capture_financial_metric_version() from public,anon,authenticated;
grant execute on function public.capture_financial_metric_version() to service_role;
drop trigger if exists financial_metric_version_capture on public.financial_metrics;
create trigger financial_metric_version_capture after insert or update on public.financial_metrics
for each row execute function public.capture_financial_metric_version();
insert into public.financial_metric_versions(company_id,period_end,period_type,fingerprint,provenance,snapshot)
select f.company_id,f.period_end,f.period_type,md5((to_jsonb(f)-'id'-'captured_at')::text),
 'baseline_observed_now',to_jsonb(f) from public.financial_metrics f
on conflict(company_id,period_end,period_type,fingerprint) do nothing;
