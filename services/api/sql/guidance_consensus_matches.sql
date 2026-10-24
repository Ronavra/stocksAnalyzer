-- New observations of an explicit fiscal-target match, never retroactive rewrites.
create table if not exists public.guidance_consensus_matches(
 id bigint generated always as identity primary key,
 guidance_event_id bigint not null references public.corporate_guidance_events(id),
 estimate_snapshot_id bigint not null references public.estimate_snapshots(id),
 metric text not null check(metric in ('eps','revenue')),
 fiscal_period_end date not null,
 accounting_basis text not null,
 currency text not null,
 consensus numeric not null,
 guidance_midpoint numeric not null,
 observed_at timestamptz not null default now(),
 evidence jsonb not null,
 unique(guidance_event_id,estimate_snapshot_id,metric)
);
create index if not exists guidance_matches_event_idx on public.guidance_consensus_matches(guidance_event_id,observed_at);
alter table public.guidance_consensus_matches enable row level security;
revoke all on public.guidance_consensus_matches from public,anon,authenticated,service_role;
grant select,insert on public.guidance_consensus_matches to service_role;
grant usage,select on sequence public.guidance_consensus_matches_id_seq to service_role;
