-- Audits/repairs cover [p_since, p_since+100); iterate for older history.
-- Exact-session labels. Never count duplicate provider rows as market days.
create or replace function public.expected_price_labels(p_since date)
returns table(company_id bigint,feature_date date,horizon integer,expected numeric,target_date date)
language sql stable security invoker set search_path='' as $$
 with bars as materialized (
  select distinct on(p.company_id,p.price_date) p.company_id,p.price_date,p.close
  from public.price_history p where p.price_date>=p_since and p.price_date<p_since+160
  order by p.company_id,p.price_date,(p.source='twelvedata') desc,p.source
 ), calendar as (
  select price_date,lead(price_date,5) over(order by price_date) d5,
   lead(price_date,10) over(order by price_date) d10,
   lead(price_date,20) over(order by price_date) d20
  from bars where company_id=(select id from public.companies where ticker='SPY' limit 1)
 )
 select f.company_id,f.feature_date,h.horizon,
  case when b.close>0 and f.close>0 then b.close/f.close-1 end,h.target_date
 from public.price_features f join calendar c on c.price_date=f.feature_date
 cross join lateral(values(5,c.d5),(10,c.d10),(20,c.d20)) h(horizon,target_date)
 left join bars b on b.company_id=f.company_id and b.price_date=h.target_date
 where f.feature_date>=p_since and f.feature_date<p_since+100
$$;
revoke all on function public.expected_price_labels(date) from public,anon,authenticated;
grant execute on function public.expected_price_labels(date) to service_role;

create or replace function public.price_session_quality(p_since date)
returns jsonb language sql stable security invoker set search_path='' as $$
 with expected as materialized (select * from public.expected_price_labels(p_since)),
 checked as (
  select e.*,case e.horizon when 5 then f.forward_return_5d when 10 then f.forward_return_10d else f.forward_return_20d end stored,
   case e.horizon when 5 then f.forward_up_5d when 10 then f.forward_up_10d else f.forward_up_20d end direction
  from expected e join public.price_features f on f.company_id=e.company_id and f.feature_date=e.feature_date
 ), sessions as (
  select distinct price_date from public.price_history
  where company_id=(select id from public.companies where ticker='SPY' limit 1) and price_date>=p_since and price_date<p_since+100
 ), bounds as (
  select p.company_id,min(p.price_date) first_date,max(p.price_date) last_date
  from public.price_history p join public.companies c on c.id=p.company_id
  where c.is_sp500 or c.scoring_profile='benchmark' group by p.company_id
 ), gaps as (
  select b.company_id,c.ticker,min(s.price_date) first_missing,max(s.price_date) last_missing,count(*) missing_sessions
  from bounds b join public.companies c on c.id=b.company_id
  join sessions s on s.price_date between b.first_date and b.last_date
  where not exists(select 1 from public.price_history p where p.company_id=b.company_id and p.price_date=s.price_date)
  group by b.company_id,c.ticker
 )
 select jsonb_build_object('since',p_since,'until',p_since+99,'checked_labels',(select count(*) from checked),
  'incorrect_labels',(select count(*) from checked where
    (expected is null and stored is not null) or (expected is not null and (stored is null or abs(stored-expected)>0.00000001))
    or direction is distinct from (case when expected is not null then expected>0 end)),
  'missing_mature_closes',(select count(*) from checked where target_date is not null and expected is null),
  'gaps',coalesce((select jsonb_agg(to_jsonb(g) order by ticker) from gaps g),'[]'::jsonb))
$$;
revoke all on function public.price_session_quality(date) from public,anon,authenticated;
grant execute on function public.price_session_quality(date) to service_role;

create or replace function public.repair_price_feature_labels(p_since date)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare changed integer;
begin
 with expected as (
  select company_id,feature_date,max(expected) filter(where horizon=5) f5,
   max(expected) filter(where horizon=10) f10,max(expected) filter(where horizon=20) f20
  from public.expected_price_labels(p_since) group by company_id,feature_date
 ), updated as (
  update public.price_features f set forward_return_5d=e.f5,forward_up_5d=(e.f5>0),
   forward_return_10d=e.f10,forward_up_10d=(e.f10>0),forward_return_20d=e.f20,forward_up_20d=(e.f20>0)
  from expected e where f.company_id=e.company_id and f.feature_date=e.feature_date and (
   (e.f5 is null and f.forward_return_5d is not null) or (e.f5 is not null and (f.forward_return_5d is null or abs(f.forward_return_5d-e.f5)>0.00000001))
   or (e.f10 is null and f.forward_return_10d is not null) or (e.f10 is not null and (f.forward_return_10d is null or abs(f.forward_return_10d-e.f10)>0.00000001))
   or (e.f20 is null and f.forward_return_20d is not null) or (e.f20 is not null and (f.forward_return_20d is null or abs(f.forward_return_20d-e.f20)>0.00000001))
   or f.forward_up_5d is distinct from (e.f5>0) or f.forward_up_10d is distinct from (e.f10>0) or f.forward_up_20d is distinct from (e.f20>0)
  ) returning f.company_id
 ) select count(*) into changed from updated;
 return jsonb_build_object('updated_feature_rows',changed,'since',p_since);
end $$;
revoke all on function public.repair_price_feature_labels(date) from public,anon,authenticated;
grant execute on function public.repair_price_feature_labels(date) to service_role;
