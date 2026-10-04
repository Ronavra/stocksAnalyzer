-- Service-only history checks use 30-day windows and exact SPY sessions.
-- Ingestion uses the lighter gap audit over its independent 90-day lookback.
create index if not exists price_history_market_date_idx on public.price_history(price_date,company_id,source) include(close);

create or replace function public.price_label_checks(p_since date)
returns table(company_id bigint,feature_date date,horizon integer,target_date date,expected numeric,stored numeric,direction boolean)
language sql stable security invoker set search_path='' set work_mem='16MB' as $$
 with bars as materialized (
  select distinct on(p.company_id,p.price_date) p.company_id,p.price_date,p.close
  from public.price_history p where p.price_date>=p_since and p.price_date<p_since+90
  order by p.company_id,p.price_date,(p.source='twelvedata') desc,p.source
 ), calendar as (
  select price_date,lead(price_date,5) over(order by price_date) d5,
   lead(price_date,10) over(order by price_date) d10,
   lead(price_date,20) over(order by price_date) d20
  from bars where company_id=(select id from public.companies where ticker='SPY' limit 1)
 )
 select f.company_id,f.feature_date,h.horizon,h.target_date,
  case when b.close>0 and f.close>0 then b.close/f.close-1 end,h.stored,h.direction
 from public.price_features f join calendar c on c.price_date=f.feature_date
 cross join lateral(values
  (5,c.d5,f.forward_return_5d,f.forward_up_5d),
  (10,c.d10,f.forward_return_10d,f.forward_up_10d),
  (20,c.d20,f.forward_return_20d,f.forward_up_20d)
 ) h(horizon,target_date,stored,direction)
 left join bars b on b.company_id=f.company_id and b.price_date=h.target_date
 where f.feature_date>=p_since and f.feature_date<p_since+30
$$;
revoke all on function public.price_label_checks(date) from public,anon,authenticated;
grant execute on function public.price_label_checks(date) to service_role;

create or replace function public.expected_price_labels(p_since date)
returns table(company_id bigint,feature_date date,horizon integer,expected numeric,target_date date)
language sql stable security invoker set search_path='' set work_mem='16MB' as $$
 select company_id,feature_date,horizon,expected,target_date from public.price_label_checks(p_since)
$$;
revoke all on function public.expected_price_labels(date) from public,anon,authenticated;
grant execute on function public.expected_price_labels(date) to service_role;

create or replace function public.price_history_gaps(p_since date,p_until date)
returns jsonb language sql stable security invoker set search_path='' as $$
 with sessions as (
  select distinct price_date from public.price_history
  where company_id=(select id from public.companies where ticker='SPY' limit 1)
   and price_date between p_since and p_until
 ), bounds as (
  select c.id company_id,c.ticker,first_bar.price_date first_date,last_bar.price_date last_date
  from public.companies c
  cross join lateral(select p.price_date from public.price_history p where p.company_id=c.id order by p.price_date limit 1) first_bar
  cross join lateral(select p.price_date from public.price_history p where p.company_id=c.id order by p.price_date desc limit 1) last_bar
  where c.is_sp500 or c.scoring_profile='benchmark'
 ), gaps as (
  select b.company_id,b.ticker,min(s.price_date) first_missing,max(s.price_date) last_missing,count(*) missing_sessions
  from bounds b join sessions s on s.price_date between b.first_date and b.last_date
  where not exists(select 1 from public.price_history p where p.company_id=b.company_id and p.price_date=s.price_date)
  group by b.company_id,b.ticker
 )
 select coalesce(jsonb_agg(to_jsonb(g) order by ticker),'[]'::jsonb) from gaps g
$$;
revoke all on function public.price_history_gaps(date,date) from public,anon,authenticated;
grant execute on function public.price_history_gaps(date,date) to service_role;

create or replace function public.price_session_quality(p_since date)
returns jsonb language sql stable security invoker set search_path='' set work_mem='16MB' as $$
 with checked as materialized(select * from public.price_label_checks(p_since))
 select jsonb_build_object('since',p_since,'until',p_since+29,
  'checked_labels',(select count(*) from checked),
  'incorrect_labels',(select count(*) from checked where
   (expected is null and stored is not null) or (expected is not null and (stored is null or abs(stored-expected)>0.00000001))
   or direction is distinct from (case when expected is not null then expected>0 end)),
  'missing_mature_closes',(select count(*) from checked where target_date is not null and expected is null),
  'gaps',public.price_history_gaps(p_since,p_since+29))
$$;
revoke all on function public.price_session_quality(date) from public,anon,authenticated;
grant execute on function public.price_session_quality(date) to service_role;

create or replace function public.repair_price_feature_labels(p_since date)
returns jsonb language plpgsql security invoker set search_path='' set work_mem='16MB' as $$
declare changed integer;
begin
 with checks as materialized(select * from public.price_label_checks(p_since)),
 expected as (
  select company_id,feature_date,max(expected) filter(where horizon=5) f5,
   max(expected) filter(where horizon=10) f10,max(expected) filter(where horizon=20) f20
  from checks group by company_id,feature_date having bool_or(
   (expected is null and stored is not null) or (expected is not null and (stored is null or abs(stored-expected)>0.00000001))
   or direction is distinct from (case when expected is not null then expected>0 end))
 ), updated as (
  update public.price_features f set forward_return_5d=e.f5,forward_up_5d=(e.f5>0),
   forward_return_10d=e.f10,forward_up_10d=(e.f10>0),forward_return_20d=e.f20,forward_up_20d=(e.f20>0)
  from expected e where f.company_id=e.company_id and f.feature_date=e.feature_date
  returning f.company_id
 ) select count(*) into changed from updated;
 return jsonb_build_object('updated_feature_rows',changed,'since',p_since,'until',p_since+29);
end $$;
revoke all on function public.repair_price_feature_labels(date) from public,anon,authenticated;
grant execute on function public.repair_price_feature_labels(date) to service_role;
