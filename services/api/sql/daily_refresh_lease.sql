create or replace function public.expire_daily_market_refreshes()
returns integer language plpgsql security invoker set search_path='' as $$
declare affected integer;
begin
 perform pg_advisory_xact_lock(hashtextextended('daily-market-refresh-lease',0));
 update public.pipeline_runs set status='error',finished_at=clock_timestamp(),
  error_message='Daily refresh lease expired after 195 minutes; safe to retry',
  metadata=coalesce(metadata,'{}'::jsonb)||jsonb_build_object('lease_expired',true)
 where pipeline='daily_market_research' and status='running'
  and started_at<=clock_timestamp()-interval '195 minutes';
 get diagnostics affected=row_count;
 return affected;
end $$;
revoke all on function public.expire_daily_market_refreshes() from public,anon,authenticated;
grant execute on function public.expire_daily_market_refreshes() to service_role;

create or replace function public.claim_daily_market_refresh(p_force boolean default false)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare local_day date; new_id bigint;
begin
 local_day=(now() at time zone 'Asia/Jerusalem')::date;
 perform pg_advisory_xact_lock(hashtextextended('daily-market-refresh-lease',0));
 perform public.expire_daily_market_refreshes();
 if exists(select 1 from public.pipeline_runs where pipeline='daily_market_research'
    and (started_at at time zone 'Asia/Jerusalem')::date=local_day
    and ((status='success' and not p_force) or (status='running' and started_at>now()-interval '195 minutes'))) then
  return jsonb_build_object('run',false);
 end if;
 insert into public.pipeline_runs(pipeline,started_at,status) values('daily_market_research',now(),'running') returning id into new_id;
 return jsonb_build_object('run',true,'id',new_id);
end $$;
revoke all on function public.claim_daily_market_refresh(boolean) from public,anon,authenticated;
grant execute on function public.claim_daily_market_refresh(boolean) to service_role;

-- Older deployed workers must also be unable to resurrect an expired lease.
create or replace function public.guard_daily_refresh_lease()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 if old.pipeline='daily_market_research' then
  if old.metadata->>'lease_expired'='true' then
   return old;
  end if;
  if old.status='running' and old.started_at<=clock_timestamp()-interval '195 minutes' then
   new.status='error';
   new.finished_at=clock_timestamp();
   new.error_message='Daily refresh lease expired after 195 minutes; safe to retry';
   new.metadata=coalesce(new.metadata,'{}'::jsonb)||jsonb_build_object('lease_expired',true);
  end if;
 end if;
 return new;
end $$;
drop trigger if exists daily_refresh_lease_guard on public.pipeline_runs;
create trigger daily_refresh_lease_guard before update on public.pipeline_runs
 for each row execute function public.guard_daily_refresh_lease();
revoke all on function public.guard_daily_refresh_lease() from public,anon,authenticated;
