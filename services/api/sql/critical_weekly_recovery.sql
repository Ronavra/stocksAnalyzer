-- Explicit recovery only. Ordinary weekly publication remains immutable.
create table if not exists public.recommendation_revisions (
 id bigint generated always as identity primary key,
 signal_date date not null, replaced_at timestamptz not null default now(),
 reason text not null, replacement_version text not null,
 old_cohort jsonb not null, old_predictions jsonb not null
);
alter table public.recommendation_revisions enable row level security;
revoke all on public.recommendation_revisions from public,anon,authenticated,service_role;
grant select,insert on public.recommendation_revisions to service_role;
grant usage,select on sequence public.recommendation_revisions_id_seq to service_role;
grant update on public.recommendation_cohorts to service_role;

create or replace function public.replace_recommendation_cohort(
 p_signal_date date, p_model_version text, p_horizons integer[],
 p_predictions jsonb, p_metadata jsonb,
 p_expected_version text, p_expected_published_at timestamptz, p_reason text
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare n integer; picks integer; existing public.recommendation_cohorts; cadence jsonb;
begin
 perform pg_advisory_xact_lock(hashtextextended('recommendation-publication-clock',0));
 select * into existing from public.recommendation_cohorts where signal_date=p_signal_date;
 if existing.signal_date is null or existing.model_version is distinct from p_expected_version
  or existing.published_at is distinct from p_expected_published_at then
  raise exception 'Publication changed or does not exist; replacement aborted';
 end if;
 if p_reason is null or length(trim(p_reason))<10 or p_model_version is not distinct from p_expected_version then
  raise exception 'Replacement needs a reason and a new policy version';
 end if;
 if p_signal_date is distinct from (select max(signal_date) from public.recommendation_cohorts)
  or p_signal_date is distinct from (select max(price_date) from public.price_history
    where company_id=(select id from public.companies where ticker='SPY' limit 1) and close>0)
  or p_signal_date<(timezone('Asia/Jerusalem',clock_timestamp())::date-7)
  or exists(select 1 from public.research_predictions where signal_date=p_signal_date
     and (evaluated_at is not null or entry_price is not null or actual_return is not null)) then
  raise exception 'Only the latest unevaluated market cohort can be replaced';
 end if;
 -- Lock evaluation rows too: an evaluator cannot set an entry during replacement.
 perform 1 from public.research_predictions where signal_date=p_signal_date for update;
 if exists(select 1 from public.research_predictions where signal_date=p_signal_date
     and (evaluated_at is not null or entry_price is not null or actual_return is not null)) then
  raise exception 'Cohort evaluation has already started';
 end if;
 if p_model_version is null or p_signal_date is null or cardinality(p_horizons)=0
  or p_horizons is null or not (p_horizons <@ array[5,10,20])
  or cardinality(p_horizons)<>(select count(distinct h) from unnest(p_horizons) h)
  or jsonb_typeof(p_predictions) is distinct from 'array' then
  raise exception 'Invalid cohort contract';
 end if;
 cadence=existing.metadata->'publication_cadence';
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
 if picks=0 then
  raise exception 'Empty replacement refused; existing publication preserved';
 end if;
 insert into public.recommendation_revisions(signal_date,reason,old_cohort,old_predictions,replacement_version)
 select p_signal_date,p_reason,to_jsonb(existing),coalesce(jsonb_agg(to_jsonb(r) order by r.id),'[]'::jsonb),p_model_version
 from public.research_predictions r where r.signal_date=p_signal_date;
 delete from public.research_predictions where signal_date=p_signal_date;
 insert into public.research_predictions(company_id,signal_date,horizon_days,signal,rank,
  research_score,historical_up_rate,historical_median_return,sample_size,catalyst,model_version,
  model_probability_up,model_expected_return,model_calibration_brier,model_baseline_brier,
  model_feature_coverage,model_diagnostics)
 select company_id,signal_date,horizon_days,signal,rank,research_score,historical_up_rate,
  historical_median_return,sample_size,catalyst,model_version,model_probability_up,
  model_expected_return,model_calibration_brier,model_baseline_brier,model_feature_coverage,model_diagnostics
 from jsonb_populate_recordset(null::public.research_predictions,p_predictions);
 update public.recommendation_cohorts set model_version=p_model_version,horizons=p_horizons,
  expected_picks=picks,status='published',published_at=clock_timestamp(),
  metadata=p_metadata||jsonb_build_object('publication_cadence',cadence,'replacement_reason',p_reason,
   'replaced_version',p_expected_version,'replaced_published_at',p_expected_published_at)
 where signal_date=p_signal_date;
 insert into public.pipeline_runs(pipeline,status,started_at,finished_at,metadata)
 values('weekly_financial_replacement','success',now(),now(),p_metadata);
 return jsonb_build_object('status','replaced','expected_picks',picks,'rows',n);
end $$;
revoke all on function public.replace_recommendation_cohort(date,text,integer[],jsonb,jsonb,text,timestamptz,text) from public,anon,authenticated;
grant execute on function public.replace_recommendation_cohort(date,text,integer[],jsonb,jsonb,text,timestamptz,text) to service_role;
