-- Immutable observations; provider month is distinct from actual capture time.
create table public.analyst_consensus_snapshots (
  company_id bigint not null references public.companies(id) on delete cascade,
  source text not null check (source in ('yahoo_finance','finnhub')),
  observed_at timestamptz not null,
  period_date date not null,
  strong_buy integer not null check (strong_buy >= 0),
  buy integer not null check (buy >= 0),
  hold integer not null check (hold >= 0),
  sell integer not null check (sell >= 0),
  strong_sell integer not null check (strong_sell >= 0),
  target_low numeric,
  target_mean numeric,
  target_median numeric,
  target_high numeric,
  primary key (company_id, source, observed_at, period_date),
  check (strong_buy + buy + hold + sell + strong_sell > 0),
  check (period_date <= observed_at::date)
);
create index analyst_consensus_observed_idx on public.analyst_consensus_snapshots (observed_at desc, company_id);
alter table public.analyst_consensus_snapshots enable row level security;
revoke all on public.analyst_consensus_snapshots from public, anon, authenticated, service_role;
grant select, insert on public.analyst_consensus_snapshots to service_role;
