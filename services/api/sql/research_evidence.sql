-- Append-only evidence; publication and first collection are distinct clocks.
create table if not exists public.research_documents (
 id bigint generated always as identity primary key,
 company_id bigint not null references public.companies(id),
 kind text not null check (kind in ('earnings_release','transcript','presentation','official_release')),
 source text not null, source_url text not null,
 source_record_id text not null, published_at timestamptz,
 observed_at timestamptz not null, title text not null,
 content text not null, content_hash text not null,
 truncated boolean not null default false,
 unique(company_id,source_url,content_hash)
);
create index if not exists research_documents_company_idx on public.research_documents(company_id,observed_at desc);
create table if not exists public.research_evidence_events (
 id bigint generated always as identity primary key,
 company_id bigint not null references public.companies(id),
 kind text not null check(kind in ('insider_transaction','institutional_holding','dividend','split','sector_kpi','material_event')),
 source text not null, source_record_id text not null, source_url text not null,
 event_date date, published_at timestamptz, observed_at timestamptz not null,
 fingerprint text not null, payload jsonb not null,
 unique(company_id,kind,source,source_record_id,fingerprint)
);
create index if not exists research_evidence_company_idx on public.research_evidence_events(company_id,kind,observed_at desc);
create table if not exists public.research_collection_checks (
 id bigint generated always as identity primary key,
 company_id bigint references public.companies(id),
 family text not null, source text not null,
 status text not null check(status in ('success','partial','error','not_configured','unavailable')),
 checked_at timestamptz not null, metadata jsonb not null default '{}'::jsonb
);
create index if not exists research_checks_company_idx on public.research_collection_checks(company_id,family,source,checked_at desc);
create index if not exists research_checks_global_idx on public.research_collection_checks(family,source,checked_at desc) where company_id is null;
create table if not exists public.macro_observations (
 id bigint generated always as identity primary key,
 series_id text not null, observation_date date not null,
 value double precision not null, units text not null, source text not null,
 vintage_date date, observed_at timestamptz not null,
 source_url text not null, fingerprint text not null,
 unique(series_id,observation_date,source,fingerprint)
);
create index if not exists macro_series_date_idx on public.macro_observations(series_id,observation_date desc,observed_at desc);
create table if not exists public.economic_calendar_observations (
 id bigint generated always as identity primary key,
 source text not null, source_record_id text not null, source_url text not null,
 event_at timestamptz not null, title text not null,
 observed_at timestamptz not null, fingerprint text not null,
 unique(source,source_record_id,observed_at)
);
create index if not exists economic_calendar_event_idx on public.economic_calendar_observations(event_at,observed_at desc);
alter table public.company_disclosures add column if not exists documents_collected_at timestamptz;
alter table public.company_disclosures add column if not exists document_status text;
alter table public.company_disclosures add column if not exists ownership_parsed_at timestamptz;
alter table public.company_disclosures add column if not exists ownership_status text;
do $$ declare t text; begin
 foreach t in array array['research_documents','research_evidence_events','research_collection_checks','macro_observations','economic_calendar_observations'] loop
  execute format('alter table public.%I enable row level security',t);
  execute format('revoke all on public.%I from public,anon,authenticated,service_role',t);
  execute format('grant select,insert on public.%I to service_role',t);
  execute format('grant usage,select on sequence public.%I to service_role',t||'_id_seq');
 end loop;
end $$;

create or replace function public.research_evidence_inventory(p_company_id bigint default null)
returns jsonb language sql stable security invoker set search_path='' as $$
with u as (select id,ticker from public.companies where active and is_sp500 and (p_company_id is null or id=p_company_id)),
docs as (
 select d.company_id,count(*) releases,
 count(*) filter(where kind in ('transcript','presentation')) call_documents,
 count(*) filter(where kind in ('transcript','presentation') and published_at is null) undated_call_documents,
 max(observed_at) observed_at
 from public.research_documents d join u on u.id=d.company_id where observed_at<=now() group by d.company_id
), events as (
 select e.company_id,count(*) filter(where kind='insider_transaction') insider_transactions,
 count(*) filter(where kind='institutional_holding') institutional_holdings,
 count(*) filter(where kind in ('dividend','split')) corporate_actions,
 max(event_date) filter(where kind='institutional_holding') holdings_report_date,
 max(observed_at) observed_at
 from public.research_evidence_events e join u on u.id=e.company_id where observed_at<=now() group by e.company_id
), checks as (
 select distinct on(c.company_id,c.family,c.source) c.* from public.research_collection_checks c
 where c.checked_at<=now() and (c.company_id is null or c.company_id in(select id from u))
 order by c.company_id,c.family,c.source,c.checked_at desc,c.id desc
), per_company as (
 select company_id,jsonb_agg(jsonb_build_object('family',family,'source',source,'status',status,'checked_at',checked_at,'metadata',metadata)) data
 from checks where company_id is not null group by company_id
), globals as (
 select coalesce(jsonb_agg(jsonb_build_object('family',family,'source',source,'status',status,'checked_at',checked_at,'metadata',metadata)),'[]'::jsonb) data
 from checks where company_id is null
), pending as (
 select d.company_id,count(*) filter(where form in('4','4/A') and ownership_parsed_at is null) insider_pending,
 count(*) filter(where form in('4','4/A') and ownership_status='error') insider_errors,
 count(*) filter(where form in('8-K','8-K/A','6-K','6-K/A') and documents_collected_at is null) documents_pending
 from public.company_disclosures d join u on u.id=d.company_id where filing_date>=current_date-90 group by d.company_id
)
select coalesce(jsonb_agg(jsonb_build_object('company_id',u.id,'documents',to_jsonb(d)-'company_id',
 'events',to_jsonb(e)-'company_id','pending',to_jsonb(p)-'company_id',
 'checks',coalesce(c.data,'[]'::jsonb),'global_checks',g.data) order by u.ticker),'[]'::jsonb)
from u left join docs d on d.company_id=u.id left join events e on e.company_id=u.id
left join pending p on p.company_id=u.id left join per_company c on c.company_id=u.id cross join globals g;
$$;
revoke all on function public.research_evidence_inventory(bigint) from public,anon,authenticated;
grant execute on function public.research_evidence_inventory(bigint) to service_role;

create or replace function public.research_macro_context()
returns jsonb language sql stable security invoker set search_path='' as $$
with latest as (
 select distinct on(series_id) series_id,observation_date,value,units,source,vintage_date,observed_at,source_url
 from public.macro_observations where observed_at<=now() and observation_date<=current_date
 order by series_id,observation_date desc,vintage_date desc nulls last,observed_at desc,id desc
), snapshot as (
 select (metadata->>'snapshot_at')::timestamptz stamp,checked_at from public.research_collection_checks
 where family='macro' and source='bls_calendar' and status='success' and checked_at<=now()
 order by checked_at desc,id desc limit 1
), upcoming as (
 select e.title,e.event_at,e.source_url,e.observed_at
 from public.economic_calendar_observations e join snapshot s on s.stamp=e.observed_at
 where e.event_at>=now() and e.event_at<=now()+interval '120 days'
 order by e.event_at limit 10
)
select jsonb_build_object('series',coalesce((select jsonb_agg(to_jsonb(l) order by series_id) from latest l),'[]'::jsonb),
 'calendar',coalesce((select jsonb_agg(to_jsonb(c) order by event_at) from upcoming c),'[]'::jsonb),
 'calendar_checked_at',(select checked_at from snapshot),'calendar_scope','BLS only; schedules can change',
 'issuer_exposures_collected',false);
$$;
revoke all on function public.research_macro_context() from public,anon,authenticated;
grant execute on function public.research_macro_context() to service_role;
