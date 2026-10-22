alter table public.estimate_snapshots add column if not exists normalization jsonb not null default '{}'::jsonb;
comment on column public.estimate_snapshots.normalization is 'Explicit source basis/currency evidence; unknown is never inferred from an issuer GAAP result.';
