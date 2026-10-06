-- Apply after research_reliability.sql. One selection per Israel Sunday week.
create or replace function public.recommendation_weekly_decision(
 p_signal_date date, p_publication_date date, p_previous_publication_date date,
 p_market_dates date[]
) returns jsonb language sql immutable security invoker set search_path='' as $$
 with clock as (
  select max(d) latest_market_date from unnest(p_market_dates) d
 ), weeks as (
  select p_publication_date-extract(dow from p_publication_date)::integer current_week,
   p_previous_publication_date-extract(dow from p_previous_publication_date)::integer previous_week
 )
 select jsonb_build_object(
  'status',case
   when p_publication_date is null then 'market_session_unavailable'
   when extract(dow from p_publication_date)<>0 then 'not_due'
   when previous_week>=current_week then 'not_due'
   when p_signal_date is null or p_signal_date is distinct from latest_market_date
    or p_signal_date<p_publication_date-3 or p_signal_date>=p_publication_date
    then 'market_session_unavailable'
   else 'due' end,
  'signal_date',p_signal_date,'publication_week_start',current_week,
  'previous_publication_week',previous_week,'latest_market_date',latest_market_date,
  'schedule','sunday','timezone','Asia/Jerusalem'
 ) from clock cross join weeks
$$;
revoke all on function public.recommendation_weekly_decision(date,date,date,date[]) from public,anon,authenticated;
grant execute on function public.recommendation_weekly_decision(date,date,date,date[]) to service_role;

create or replace function public.recommendation_publication_status(p_signal_date date)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare previous_publication_date date; market_dates date[];
 publication_date date=timezone('Asia/Jerusalem',clock_timestamp())::date;
 existing public.recommendation_cohorts;
begin
 select * into existing from public.recommendation_cohorts where signal_date=p_signal_date;
 if found then
  return jsonb_build_object('status','already_published','signal_date',p_signal_date,
   'expected_picks',existing.expected_picks);
 end if;
 -- Older Saturday freezes already served the following Sunday. Preserve them.
 select max(coalesce((metadata->'publication_cadence'->>'publication_week_start')::date,
  timezone('Asia/Jerusalem',published_at)::date+
   case when extract(dow from timezone('Asia/Jerusalem',published_at))=6 then 1 else 0 end))
 into previous_publication_date from public.recommendation_cohorts;
 select array_agg(distinct price_date order by price_date) into market_dates
 from public.price_history
 where company_id=(select id from public.companies where ticker='SPY' limit 1)
  and price_date>=publication_date-7 and close>0;
 return public.recommendation_weekly_decision(p_signal_date,publication_date,previous_publication_date,market_dates);
end $$;
revoke all on function public.recommendation_publication_status(date) from public,anon,authenticated;
grant execute on function public.recommendation_publication_status(date) to service_role;

-- Serialize different dates too, and recheck the clock inside publication.
create or replace function public.publish_recommendation_cohort(
 p_signal_date date, p_model_version text, p_horizons integer[],
 p_predictions jsonb, p_metadata jsonb
) returns jsonb language plpgsql security invoker set search_path='' as $$
declare n integer; picks integer; existing public.recommendation_cohorts; cadence jsonb;
begin
 perform pg_advisory_xact_lock(hashtextextended('recommendation-publication-clock',0));
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
 cadence=public.recommendation_publication_status(p_signal_date);
 if cadence->>'status'<>'due' then
  return cadence;
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
 values(p_signal_date,p_model_version,p_horizons,picks,case when picks=0 then 'no_picks' else 'published' end,p_metadata||jsonb_build_object('publication_cadence',cadence));
 insert into public.pipeline_runs(pipeline,status,started_at,finished_at,metadata)
 values('weekly_financial_selection','success',now(),now(),p_metadata);
 return jsonb_build_object('status','published','expected_picks',picks,'rows',n);
end $$;
revoke all on function public.publish_recommendation_cohort(date,text,integer[],jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.publish_recommendation_cohort(date,text,integer[],jsonb,jsonb) to service_role;
