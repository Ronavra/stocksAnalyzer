-- Append-only paper decisions; no public writes or brokerage execution.
create table if not exists public.active_portfolio_snapshots (
 id bigint generated always as identity primary key,
 policy text not null check (policy='active-ten-v1'),
 decision_day date not null,
 created_at timestamptz not null default now(),
 snapshot jsonb not null check (jsonb_typeof(snapshot)='object')
);
create index if not exists active_portfolio_latest_idx on public.active_portfolio_snapshots(policy,id desc);
alter table public.active_portfolio_snapshots enable row level security;
revoke all on public.active_portfolio_snapshots from public,anon,authenticated,service_role;
grant select,insert on public.active_portfolio_snapshots to service_role;
grant usage,select on sequence public.active_portfolio_snapshots_id_seq to service_role;

create or replace function public.record_active_portfolio(p_expected_revision bigint,p_snapshot jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare latest bigint; existing bigint; decision date; portfolio jsonb; position_count int; old_snapshot jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(73519253);
 decision=(p_snapshot->>'decision_day')::date;
 if decision is distinct from (now() at time zone 'America/New_York')::date then
  raise exception 'Decision must be recorded on its actual New York day';
 end if;
 select id,snapshot into existing,old_snapshot from public.active_portfolio_snapshots where policy='active-ten-v1' and decision_day=decision order by id desc limit 1;
 -- A failed research review may be repaired by a later successful review that
 -- uses the already committed positions/fills. Successful days stay frozen.
 if existing is not null and old_snapshot->'portfolio'->>'as_of_date' >= p_snapshot->'portfolio'->>'as_of_date'
    and (old_snapshot->'portfolio'->>'ranking_error' is null
    or p_snapshot->'portfolio'->>'ranking_error' is not null) then
  return jsonb_build_object('status','already_recorded','revision',existing);
 end if;
 select coalesce(max(id),0) into latest from public.active_portfolio_snapshots where policy='active-ten-v1';
 if latest is distinct from p_expected_revision then raise exception 'Portfolio changed; reload before recording'; end if;
 portfolio=p_snapshot->'portfolio';
 if portfolio is null or portfolio->>'policy' is distinct from 'active-ten-v1'
  or portfolio->>'mode' is distinct from 'paper'
  or jsonb_typeof(portfolio->'positions') is distinct from 'array'
  or jsonb_typeof(portfolio->'orders') is distinct from 'array'
  or (portfolio->>'cash') is null or (portfolio->>'cash')::numeric<0
  or (portfolio->>'cash')::numeric in ('NaN'::numeric,'Infinity'::numeric,'-Infinity'::numeric)
  or portfolio->>'validated' is distinct from 'false'
  or portfolio->>'as_of_date' is null or (portfolio->>'as_of_date')::date>decision then
  raise exception 'Invalid paper portfolio';
 end if;
 position_count=jsonb_array_length(portfolio->'positions');
 if position_count>10 or position_count<>(select count(distinct p->>'company_id') from jsonb_array_elements(portfolio->'positions') p)
  or jsonb_array_length(portfolio->'orders')>20 then raise exception 'Position/order limit exceeded'; end if;
 if exists(select 1 from jsonb_array_elements(portfolio->'positions') p
   where (p->>'shares') is null or (p->>'shares')::numeric<=0 or (p->>'shares')::numeric='NaN'::numeric)
  or exists(select 1 from jsonb_array_elements(portfolio->'orders') o
   where o->>'side' is null or o->>'side' not in ('buy','sell') or o->>'company_id' is null or o->>'execute_on' is null) then
  raise exception 'Invalid position or order';
 end if;
 insert into public.active_portfolio_snapshots(policy,decision_day,snapshot)
 values('active-ten-v1',decision,p_snapshot) returning id into existing;
 return jsonb_build_object('status','recorded','revision',existing);
end $$;
revoke all on function public.record_active_portfolio(bigint,jsonb) from public,anon,authenticated;
grant execute on function public.record_active_portfolio(bigint,jsonb) to service_role;

create or replace function public.active_portfolio_price_window(p_since date,p_until date,p_company_ids bigint[])
returns jsonb language sql stable security invoker set search_path='' as $$
 select coalesce(jsonb_agg(jsonb_build_object('company_id',company_id,'price_date',price_date,'close',close) order by price_date,company_id),'[]'::jsonb)
 from (select distinct on (company_id,price_date) company_id,price_date,close
       from public.price_history
       where company_id=any(p_company_ids) and price_date between p_since and p_until
       order by company_id,price_date,(source='twelvedata') desc,source) p
$$;
revoke all on function public.active_portfolio_price_window(date,date,bigint[]) from public,anon,authenticated;
grant execute on function public.active_portfolio_price_window(date,date,bigint[]) to service_role;
