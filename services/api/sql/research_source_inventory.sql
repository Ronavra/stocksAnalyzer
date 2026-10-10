-- Fiscal estimates are daily observations, never retrospectively backdated.
alter table public.estimate_snapshots add column if not exists relative_period text;
alter table public.estimate_snapshots add column if not exists eps_basis text not null default 'unknown';
alter table public.estimate_snapshots add column if not exists eps_currency text;
alter table public.estimate_snapshots add column if not exists revenue_currency text;
alter table public.estimate_snapshots add column if not exists provider_eps_trend jsonb not null default '{}'::jsonb;
alter table public.estimate_snapshots add column if not exists provider_eps_revisions jsonb not null default '{}'::jsonb;
create index if not exists estimate_snapshots_observed_idx on public.estimate_snapshots(company_id,captured_at desc);
alter table public.estimate_snapshots enable row level security;
revoke all on public.estimate_snapshots from public,anon,authenticated;
revoke update,delete on public.estimate_snapshots from service_role;
grant select,insert on public.estimate_snapshots to service_role;
grant usage,select on sequence public.estimate_snapshots_id_seq to service_role;

-- One bounded summary per issuer. No raw provider credentials or document
-- bodies leave the service-only function. Both issuer and universe views use
-- exactly the same inventory, rather than treating record existence as health.
create or replace function public.research_source_inventory(p_company_id bigint default null)
returns jsonb language sql stable security invoker set search_path='' as $$
with universe as (
 select id,ticker from public.companies
 where active and is_sp500 and (p_company_id is null or id=p_company_id)
), news as (
 select n.company_id,max(n.published_at) published_at,max(n.created_at) observed_at,
 count(*) filter(where n.published_at>=now()-interval '7 days') articles_7d,
 count(*) articles_90d
 from public.news_events n join universe u on u.id=n.company_id
 where n.published_at>=now()-interval '90 days' and n.published_at<=now() and n.created_at<=now()
 group by n.company_id
), disclosures as (
 select d.company_id,max(d.published_at) published_at,max(d.observed_at) observed_at,count(*) reports_90d,
 count(*) filter(where d.enriched_at is null and d.form in ('8-K','8-K/A','6-K','6-K/A')) pending,
 count(*) filter(where d.enrichment_status='error') errors,
 count(*) filter(where d.form in ('10-K','10-K/A','10-Q','10-Q/A','20-F','20-F/A','40-F','40-F/A')) financial_reports,
 count(*) filter(where d.enrichment_status='guidance_extracted') parsed_guidance
 from public.company_disclosures d join universe u on u.id=d.company_id
 where d.published_at>=now()-interval '90 days' and d.published_at<=now() and d.observed_at<=now()
 group by d.company_id
), estimates as (
 select e.company_id,max(e.captured_at) observed_at,min(e.captured_at) first_observed_at,
 count(distinct e.captured_date) observation_days,
 count(distinct (e.fiscal_period_end,e.period_type)) filter(where e.captured_at>=now()-interval '48 hours' and e.eps_consensus is not null) eps_periods,
 count(distinct (e.fiscal_period_end,e.period_type)) filter(where e.captured_at>=now()-interval '48 hours' and e.revenue_consensus is not null) revenue_periods,
 count(distinct (e.fiscal_period_end,e.period_type)) filter(where e.captured_at>=now()-interval '48 hours' and
  (e.eps_consensus<e.eps_low or e.eps_consensus>e.eps_high or e.revenue_consensus<e.revenue_low or e.revenue_consensus>e.revenue_high)) inconsistent_periods
 from public.estimate_snapshots e join universe u on u.id=e.company_id
 where e.captured_at<=now() group by e.company_id
), earnings as (
 select e.company_id,max(e.reported_date) filter(where e.reported_date<=current_date and e.reported_eps is not null) reported_date,
 min(e.reported_date) filter(where e.reported_date>=current_date and e.reported_date<=current_date+120) next_date,
 count(*) filter(where e.reported_date between current_date and current_date+120 and e.estimated_eps is not null) upcoming_eps,
 count(*) filter(where e.reported_date between current_date and current_date+120 and e.estimated_revenue is not null) upcoming_revenue
 from public.earnings_events e join universe u on u.id=e.company_id group by e.company_id
), guidance as (
 select g.company_id,max(g.event_date) event_date,max(g.captured_at) observed_at,count(*) events_90d,
 count(*) filter(where g.consensus_eps_at_event is not null or g.consensus_revenue_at_event is not null) matched_consensus
 from public.corporate_guidance_events g join universe u on u.id=g.company_id
 where g.event_date>=current_date-90 and g.event_date<=current_date and g.captured_at<=now()
 group by g.company_id
)
select coalesce(jsonb_agg(jsonb_build_object(
 'company_id',u.id,'ticker',u.ticker,'price_date',p.price_date,'feature_date',pf.feature_date,
 'financial',f.data,'valuation_date',v.snapshot_date,
 'earnings',to_jsonb(e)-'company_id','estimates',to_jsonb(es)-'company_id',
 'analyst',a.data,'news',to_jsonb(n)-'company_id',
 'disclosures',to_jsonb(d)-'company_id','guidance',to_jsonb(g)-'company_id',
 'total_return_date',tr.last_date
 ) order by u.ticker),'[]'::jsonb)
from universe u
left join lateral (select price_date from public.price_history where company_id=u.id and close>0 and price_date<=current_date order by price_date desc limit 1) p on true
left join lateral (select feature_date from public.price_features where company_id=u.id and feature_date<=current_date order by feature_date desc limit 1) pf on true
left join lateral (select jsonb_build_object('period_end',period_end,'filed_date',filed_date,'observed_at',captured_at,'source',source) data from public.financial_metrics where company_id=u.id and period_type='ttm' order by period_end desc limit 1) f on true
left join lateral (select snapshot_date from public.valuation_snapshots where company_id=u.id and snapshot_date<=current_date order by snapshot_date desc limit 1) v on true
left join lateral (select jsonb_build_object('observed_at',observed_at,'source',source,'analysts',coalesce(strong_buy,0)+coalesce(buy,0)+coalesce(hold,0)+coalesce(sell,0)+coalesce(strong_sell,0)) data from public.analyst_consensus_snapshots where company_id=u.id and observed_at<=now() and period_date<=current_date order by observed_at desc,period_date desc limit 1) a on true
left join earnings e on e.company_id=u.id
left join estimates es on es.company_id=u.id
left join news n on n.company_id=u.id
left join disclosures d on d.company_id=u.id
left join guidance g on g.company_id=u.id
left join public.portfolio_return_series tr on tr.company_id=u.id;
$$;
revoke all on function public.research_source_inventory(bigint) from public,anon,authenticated;
grant execute on function public.research_source_inventory(bigint) to service_role;
