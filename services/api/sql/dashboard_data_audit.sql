-- Aggregate large evidence tables on the server; one consistent service-only
-- snapshot replaces dozens of paged network reads for the dashboard audit.
create or replace function public.research_dashboard_data_audit()
returns jsonb language sql stable security invoker set search_path='' as $$
with u as materialized(select id from public.companies where is_sp500),
latest_analyst as materialized(
 select distinct on(a.company_id) a.* from public.analyst_consensus_snapshots a join u on u.id=a.company_id
 where a.observed_at<=now() and a.period_date<=(a.observed_at at time zone 'UTC')::date
 order by a.company_id,a.observed_at desc,a.period_date desc,a.source desc
), financial as materialized(
 select jsonb_build_object('metadata',jsonb_build_object('financial_audit',metadata->'financial_audit'),
                           'finished_at',finished_at,'status',status) data
 from public.pipeline_runs where pipeline='research_sources_refresh' and metadata @> '{"financial_audit":{}}'::jsonb
 order by started_at desc limit 1
), checks as materialized(
 select distinct on(pipeline) pipeline,status,started_at,finished_at
 from public.pipeline_runs where pipeline in('free_earnings_refresh','research_sources_refresh','company_disclosures_refresh',
 'estimate_consensus_refresh','news_refresh','sec_guidance_refresh','analyst_consensus_refresh','official_documents_refresh',
 'insider_transactions_refresh','public_ownership_actions_refresh','corporate_actions_refresh','macro_sources_refresh')
 order by pipeline,started_at desc,id desc
)
select jsonb_build_object(
 'audit',public.research_data_audit(),
 'counts',jsonb_build_object(
  'analyst_consensus',(select count(*) from latest_analyst where observed_at>=now()-interval '7 days'
   and period_date>=current_date-45 and strong_buy>=0 and buy>=0 and hold>=0 and sell>=0 and strong_sell>=0
   and strong_buy+buy+hold+sell+strong_sell>=3),
  'disclosures',(select count(distinct d.company_id) from public.company_disclosures d join u on u.id=d.company_id where published_at>=now()-interval '90 days'),
  'upcoming_eps_consensus',(select count(distinct e.company_id) from public.earnings_events e join u on u.id=e.company_id where reported_date between current_date and current_date+120 and estimated_eps is not null),
  'corporate_guidance_events',(select count(distinct g.company_id) from public.corporate_guidance_events g join u on u.id=g.company_id where event_date>=current_date-90),
  'news_events',(select count(distinct n.company_id) from public.news_events n join u on u.id=n.company_id where published_at>=current_date-90)
 ),
 'financial_report',coalesce((select data from financial),'{}'::jsonb),
 'inventory',public.research_source_inventory(null),
 'calendars',public.free_earnings_calendar(null),
 'source_checks',(select coalesce(jsonb_agg(to_jsonb(checks)),'[]'::jsonb) from checks)
);
$$;
revoke all on function public.research_dashboard_data_audit() from public,anon,authenticated;
grant execute on function public.research_dashboard_data_audit() to service_role;
