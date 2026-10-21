-- First-seen calendar observations remain separate from mutable provider events.
create table if not exists public.earnings_calendar_snapshots (
 id bigint generated always as identity primary key,
 company_id bigint not null references public.companies(id),
 source text not null check(source in ('alphavantage','yahoo_finance')),
 observed_at timestamptz not null,
 status text not null check(status in ('observed','unknown','error')),
 dates jsonb not null default '[]'::jsonb check(jsonb_typeof(dates)='array'),
 source_url text not null,
 unique(company_id,source,observed_at)
);
create index if not exists earnings_calendar_observed_idx
 on public.earnings_calendar_snapshots(company_id,source,observed_at desc,id desc);
alter table public.earnings_calendar_snapshots enable row level security;
revoke all on public.earnings_calendar_snapshots from public,anon,authenticated,service_role;
grant select,insert on public.earnings_calendar_snapshots to service_role;
grant usage,select on sequence public.earnings_calendar_snapshots_id_seq to service_role;

create or replace function public.free_earnings_calendar(p_company_ids bigint[] default null)
returns jsonb language sql stable security invoker set search_path='' as $$
select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) from (
 select distinct on(company_id,source) company_id,source,observed_at,status,dates
 from public.earnings_calendar_snapshots
 where (p_company_ids is null or company_id=any(p_company_ids)) and observed_at<=now()
 order by company_id,source,observed_at desc,id desc
) r;
$$;
revoke all on function public.free_earnings_calendar(bigint[]) from public,anon,authenticated;
grant execute on function public.free_earnings_calendar(bigint[]) to service_role;

create or replace function public.claim_free_earnings_refresh()
returns jsonb language plpgsql security invoker set search_path='' as $$
declare claimed bigint;
begin
 perform pg_advisory_xact_lock(73519251);
 update public.pipeline_runs set status='error',finished_at=now(),error_message='Free earnings collection lease expired'
 where pipeline='free_earnings_refresh' and status='running' and started_at<now()-interval '1 hour';
 if exists(select 1 from public.pipeline_runs where pipeline='free_earnings_refresh' and status='running') then
  return jsonb_build_object('run',false);
 end if;
 insert into public.pipeline_runs(pipeline,status,started_at) values('free_earnings_refresh','running',now()) returning id into claimed;
 return jsonb_build_object('run',true,'id',claimed);
end;
$$;
revoke all on function public.claim_free_earnings_refresh() from public,anon,authenticated;
grant execute on function public.claim_free_earnings_refresh() to service_role;

-- One bulk calendar request per UTC day, across GitHub and the local scheduler.
create or replace function public.claim_alpha_earnings_calendar()
returns boolean language plpgsql security invoker set search_path='' as $$
begin
 perform pg_advisory_xact_lock(73519252);
 if exists(select 1 from public.pipeline_runs where pipeline='alpha_earnings_calendar_request'
  and started_at>=(now() at time zone 'UTC')::date at time zone 'UTC') then return false; end if;
 insert into public.pipeline_runs(pipeline,status,started_at,finished_at,metadata)
 values('alpha_earnings_calendar_request','success',now(),now(),'{"outcome":"request_reserved","maximum_requests":1}'::jsonb);
 return true;
end;
$$;
revoke all on function public.claim_alpha_earnings_calendar() from public,anon,authenticated;
grant execute on function public.claim_alpha_earnings_calendar() to service_role;
