-- One atomic adjusted-price snapshot per company. Historical adjusted levels
-- can be rescaled by later corporate actions, so never append mixed vintages.
create table public.portfolio_return_series (
  company_id bigint primary key references public.companies(id) on delete cascade,
  source text not null check (source = 'twelvedata_adjust_all'),
  adjustment text not null check (adjustment = 'all'),
  observed_at timestamptz not null,
  first_date date not null,
  last_date date not null,
  bars jsonb not null check (jsonb_typeof(bars) = 'array' and jsonb_array_length(bars) > 0),
  check (last_date >= first_date)
);
alter table public.portfolio_return_series enable row level security;
revoke all on public.portfolio_return_series from public, anon, authenticated, service_role;
grant select, insert, update on public.portfolio_return_series to service_role;
comment on table public.portfolio_return_series is
  'Evaluation-only split/dividend adjusted closes. Not execution quotes or historical training observations.';
