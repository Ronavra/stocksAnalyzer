-- Research pilot ledger. These are assumed opening-price fills, never broker confirmations.
create table if not exists public.research_pilots (
 pilot_id text primary key,
 cohort_date date not null references public.recommendation_cohorts(signal_date),
 trade_date date not null,
 benchmark text not null default 'SPY' check (benchmark='SPY'),
 status text not null default 'pending_open' check(status in ('pending_open','simulated','incomplete')),
 created_at timestamptz not null default now(),
 note text not null default 'Assumed market-open entry; not a broker-confirmed purchase'
);
create table if not exists public.research_pilot_positions (
 pilot_id text not null references public.research_pilots(pilot_id),
 company_id bigint not null references public.companies(id),
 ticker text not null,
 rank integer not null check(rank between 1 and 5),
 target_usd numeric not null check(target_usd>0),
 entry_open numeric check(entry_open>0),
 entry_shares numeric check(entry_shares>0),
 entry_observed_at timestamptz,
 primary key(pilot_id,company_id),
 unique(pilot_id,rank),
 check((entry_open is null and entry_shares is null and entry_observed_at is null) or
       (entry_open is not null and entry_shares is not null and entry_observed_at is not null))
);
create table if not exists public.research_pilot_marks (
 pilot_id text not null references public.research_pilots(pilot_id),
 price_date date not null,
 ticker text not null,
 close numeric not null check(close>0),
 observed_at timestamptz not null default now(),
 primary key(pilot_id,price_date,ticker)
);
create index if not exists research_pilot_marks_lookup on public.research_pilot_marks(pilot_id,price_date);
alter table public.research_pilots enable row level security;
alter table public.research_pilot_positions enable row level security;
alter table public.research_pilot_marks enable row level security;
revoke all on public.research_pilots,public.research_pilot_positions,public.research_pilot_marks from public,anon,authenticated;
grant select,insert,update on public.research_pilots,public.research_pilot_positions,public.research_pilot_marks to service_role;
-- Do not grant DELETE: selection, entries and observed marks are historical evidence.
