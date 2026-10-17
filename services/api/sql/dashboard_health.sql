-- Compact, service-only snapshot: one round trip for dashboard health.
create or replace function public.research_system_health_snapshot(p_expected_market_date date,p_ranker_version text)
returns jsonb language sql stable security invoker set search_path='' as $$
 with latest_runs as (
  select distinct on (r.pipeline) r.pipeline,
   (to_jsonb(r)-'metadata')||jsonb_build_object('metadata',case r.pipeline when 'weekly_financial_comparison' then r.metadata-'cohorts' when 'research_history_repair' then jsonb_build_object('latest_quality',r.metadata->'latest_quality') else r.metadata-'financial_audit' end) as summary
  from public.pipeline_runs r
  where r.pipeline=any(array['daily_market_research','research_sources_refresh','weekly_financial_comparison',
   'analyst_consensus_refresh','research_enrichment','independent_daily_deadline','research_history_repair'])
   and (r.pipeline<>'research_history_repair' or r.status='success')
  order by r.pipeline,r.started_at desc,r.id desc
 ), universe as (
  select id,ticker from public.companies where is_sp500 or scoring_profile='benchmark'
 ), fresh as (
  select u.*,
   exists(select 1 from public.price_history p where p.company_id=u.id and p.price_date=p_expected_market_date
    and p.close>0 and p.close::text not in ('NaN','Infinity','-Infinity')) as price_ok,
   exists(select 1 from public.price_features f where f.company_id=u.id and f.feature_date=p_expected_market_date
    and f.close>0 and f.close::text not in ('NaN','Infinity','-Infinity')) as feature_ok
  from universe u
 ), counts as (
  select count(*) total,count(*) filter(where price_ok) prices,count(*) filter(where feature_ok) features,
   coalesce(jsonb_agg(ticker order by ticker) filter(where not price_ok),'[]'::jsonb) missing_prices,
   coalesce(jsonb_agg(ticker order by ticker) filter(where not feature_ok),'[]'::jsonb) missing_features from fresh
 )
 select jsonb_build_object(
  'checked_at',now(),'model_readiness',public.research_model_readiness(),'runs',(select jsonb_object_agg(pipeline,summary) from latest_runs),
  'model_run',(select jsonb_build_object('started_at',started_at,'finished_at',finished_at,'status',status,'model_version',model_version,
    'best_stage',best_stage,'best_groups',best_groups,'error_message',error_message,'results',case when best_stage is not null then jsonb_build_object(best_stage,results->best_stage) end)
    from public.model_validation_runs where model_version<>p_ranker_version order by started_at desc,id desc limit 1),
  'ranker_run',(select jsonb_build_object('started_at',started_at,'finished_at',finished_at,'status',status,'model_version',model_version,
    'best_stage',best_stage,'error_message',error_message,'results',results-array['holdout_cohorts','selection_variants','features'])
    from public.model_validation_runs where model_version=p_ranker_version order by started_at desc,id desc limit 1),
  'latest_price_date',(select max(price_date) from public.price_history),
  'latest_feature_date',(select max(feature_date) from public.price_features),
  'audit',public.research_data_audit(),
  'freshness',jsonb_build_object('ok',total>=500 and prices=total and features=total,
   'expected_market_date',p_expected_market_date,'latest_price_date',case when prices>0 then p_expected_market_date end,
   'latest_feature_date',case when features>0 then p_expected_market_date end,
   'price_companies',prices,'feature_companies',features,'universe_companies',total,
   'missing_prices',missing_prices,'missing_features',missing_features,
   'error_message',case when total<500 or prices<>total or features<>total
    then format('Freshness validation failed: expected %s; universe=%s; prices=%s; features=%s',p_expected_market_date,total,prices,features) end)
 ) from counts;
$$;
revoke all on function public.research_system_health_snapshot(date,text) from public,anon,authenticated;
grant execute on function public.research_system_health_snapshot(date,text) to service_role;
