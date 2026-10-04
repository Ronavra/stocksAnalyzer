-- Free official company disclosures, separate from news sentiment or forecasts.
create table if not exists public.company_disclosures (
 id bigint generated always as identity primary key,
 company_id bigint not null references public.companies(id),
 accession_number text not null,
 form text not null,
 filing_date date not null,
 published_at timestamptz not null,
 observed_at timestamptz not null,
 items text[] not null default '{}',
 headline text not null,
 source_url text not null,
 unique(company_id,accession_number)
);
create index if not exists company_disclosures_recent_idx on public.company_disclosures(company_id,published_at desc);
alter table public.company_disclosures enable row level security;
revoke all on public.company_disclosures from public,anon,authenticated;
grant select,insert,update on public.company_disclosures to service_role;
grant usage,select on sequence public.company_disclosures_id_seq to service_role;
