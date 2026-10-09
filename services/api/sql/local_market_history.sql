-- Inactive by default. Only a verified archive migration enables retention.
create table if not exists public.market_history_storage (
  id integer primary key check (id=1), enabled boolean not null default false,
  price_days integer not null default 400 check (price_days>=400),
  feature_days integer not null default 1100 check (feature_days>=1100),
  project_ref text, archived_at timestamptz, archive_fingerprint text
);
alter table public.market_history_storage enable row level security;
revoke all on public.market_history_storage from public,anon,authenticated;
grant select,insert,update on public.market_history_storage to service_role;
insert into public.market_history_storage(id) values(1) on conflict(id) do nothing;

-- Runs as the table owner so anon reads never need access to the policy table.
-- There is no public callable definer RPC; this function is trigger-only.
create or replace function public.enforce_market_history_retention()
returns trigger language plpgsql security definer set search_path=pg_catalog,public as $$
declare policy public.market_history_storage; oldest date; row_date date;
begin
  select * into policy from public.market_history_storage where id=1;
  if not found or not policy.enabled then return new; end if;
  if tg_table_name='price_history' then
    oldest=(clock_timestamp() at time zone 'Asia/Jerusalem')::date-policy.price_days;
    row_date=new.price_date;
  else
    oldest=(clock_timestamp() at time zone 'Asia/Jerusalem')::date-policy.feature_days;
    row_date=new.feature_date;
  end if;
  if row_date<oldest then
    raise exception 'History older than % belongs in LOCAL_MARKET_ARCHIVE; cloud retention rejects an unarchived write',oldest;
  end if;
  return new;
end $$;
revoke all on function public.enforce_market_history_retention() from public,anon,authenticated,service_role;
drop trigger if exists market_history_retention on public.price_history;
create trigger market_history_retention before insert or update on public.price_history
for each row execute function public.enforce_market_history_retention();
drop trigger if exists market_history_retention on public.price_features;
create trigger market_history_retention before insert or update on public.price_features
for each row execute function public.enforce_market_history_retention();
