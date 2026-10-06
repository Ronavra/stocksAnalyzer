-- Supplemental reported bank / balance-sheet evidence is included in the
-- existing append-only financial version trigger automatically.
alter table public.financial_metrics add column if not exists supplemental jsonb not null default '{}'::jsonb;
alter table public.corporate_guidance_events add column if not exists published_at timestamptz;
alter table public.corporate_guidance_events add column if not exists source_url text;
alter table public.corporate_guidance_events add column if not exists evidence jsonb;
alter table public.news_events add column if not exists source_record_id text;
alter table public.news_events add column if not exists publisher text;
alter table public.news_events add column if not exists sentiment_method text;
alter table public.company_disclosures add column if not exists enriched_at timestamptz;
alter table public.company_disclosures add column if not exists enrichment_status text;
create unique index if not exists news_events_source_record_idx on public.news_events(company_id,source,source_record_id);
create index if not exists news_events_observed_idx on public.news_events(created_at,company_id,published_at);
create index if not exists guidance_observed_idx on public.corporate_guidance_events(captured_at,company_id,event_date);
create index if not exists disclosures_pending_idx on public.company_disclosures(filing_date desc) where enriched_at is null;

-- A database claim also prevents simultaneous GitHub and local schedulers
-- from downloading the same daily prices. Failed attempts remain retryable.
create or replace function public.claim_daily_market_refresh(p_force boolean default false)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare local_day date; new_id bigint;
begin
 local_day=(now() at time zone 'Asia/Jerusalem')::date;
 perform pg_advisory_xact_lock(hashtextextended('daily-refresh:'||local_day::text,0));
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

-- Existing research source tables are service-only. Never expose raw facts or
-- provider metadata directly to browser clients.
alter table public.news_events enable row level security;
alter table public.corporate_guidance_events enable row level security;
revoke all on public.news_events,public.corporate_guidance_events from public,anon,authenticated;
grant select,insert,update on public.news_events,public.corporate_guidance_events to service_role;
grant usage,select on sequence public.news_events_id_seq,public.corporate_guidance_events_id_seq to service_role;

create table if not exists public.model_forecasts (
 id bigint generated always as identity primary key,
 company_id bigint not null references public.companies(id),
 feature_date date not null,
 horizon_days integer not null check(horizon_days in (5,10,20)),
 model_version text not null,
 validation_run_id bigint not null references public.model_validation_runs(id),
 generated_at timestamptz not null default now(),
 probability_up numeric not null check(probability_up between 0 and 1),
 expected_return numeric,
 feature_coverage numeric not null check(feature_coverage between 0 and 1),
 diagnostics jsonb not null,
 unique(company_id,feature_date,horizon_days,model_version,validation_run_id)
);
create index if not exists model_forecasts_company_recent_idx on public.model_forecasts(company_id,feature_date desc,generated_at desc);
alter table public.model_forecasts enable row level security;
revoke all on public.model_forecasts from public,anon,authenticated;
grant select,insert on public.model_forecasts to service_role;
grant usage,select on sequence public.model_forecasts_id_seq to service_role;

-- Independent deadline evidence: this monitor runs in Postgres even when
-- GitHub Actions is delayed. It does not require vendor or GitHub credentials.
create extension if not exists pg_cron;
create schema if not exists research_internal;
revoke all on schema research_internal from public,anon,authenticated;
create or replace function research_internal.check_daily_deadline(p_now timestamptz default now())
returns jsonb language plpgsql security invoker set search_path='' as $$
declare local_day date; deadline timestamptz; first_run timestamptz; completed timestamptz; result jsonb;
begin
 local_day=(p_now at time zone 'Asia/Jerusalem')::date;
 deadline=(local_day+time '12:00') at time zone 'Asia/Jerusalem';
 if p_now<deadline then return jsonb_build_object('status','before_deadline'); end if;
 perform pg_advisory_xact_lock(hashtextextended('daily-deadline:'||local_day::text,0));
 select metadata into result from public.pipeline_runs
 where pipeline='independent_daily_deadline' and expected_market_date=local_day limit 1;
 if found then return result; end if;
 select min(started_at),min(finished_at) filter(where status='success' and finished_at<=deadline)
 into first_run,completed from public.pipeline_runs
 where pipeline='daily_market_research' and (started_at at time zone 'Asia/Jerusalem')::date=local_day;
 result=jsonb_build_object('local_date',local_day,'deadline',deadline,'on_time',completed is not null,
                          'first_started_at',first_run,'completed_by_deadline',completed,
                          'monitor_provider','supabase_cron','checked_at',p_now);
 insert into public.pipeline_runs(pipeline,status,started_at,finished_at,expected_market_date,metadata,error_message)
 values('independent_daily_deadline',case when completed is not null then 'success' else 'error' end,p_now,p_now,local_day,result,
        case when completed is null then 'No successful daily market refresh by 12:00 Asia/Jerusalem' else null end);
 return result;
end $$;
revoke all on function research_internal.check_daily_deadline(timestamptz) from public,anon,authenticated;
-- Hourly checks are DST-safe; the function records exactly one daily deadline.
select cron.schedule('stocks-analyzer-independent-deadline','17 * * * *','select research_internal.check_daily_deadline();');

-- Preserve expected earnings dates and revisions at their actual observation
-- time. The baseline is observed now, never on the historical report date.
create table if not exists public.earnings_event_versions (
 id bigint generated always as identity primary key,
 event_id bigint not null,
 company_id bigint not null references public.companies(id),
 fingerprint text not null,
 observed_at timestamptz not null default now(),
 provenance text not null,
 snapshot jsonb not null,
 unique(event_id,fingerprint)
);
create index if not exists earnings_versions_asof_idx on public.earnings_event_versions(company_id,observed_at);
alter table public.earnings_event_versions enable row level security;
revoke all on public.earnings_event_versions from public,anon,authenticated;
grant select,insert on public.earnings_event_versions to service_role;
grant usage,select on sequence public.earnings_event_versions_id_seq to service_role;
create or replace function public.capture_earnings_event_version()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
 insert into public.earnings_event_versions(event_id,company_id,fingerprint,provenance,snapshot)
 values(new.id,new.company_id,md5((to_jsonb(new)-'id'-'captured_at')::text),'live_ingestion',to_jsonb(new))
 on conflict(event_id,fingerprint) do nothing;
 return new;
end $$;
revoke all on function public.capture_earnings_event_version() from public,anon,authenticated;
grant execute on function public.capture_earnings_event_version() to service_role;
drop trigger if exists earnings_event_version_capture on public.earnings_events;
create trigger earnings_event_version_capture after insert or update on public.earnings_events
for each row execute function public.capture_earnings_event_version();
insert into public.earnings_event_versions(event_id,company_id,fingerprint,provenance,snapshot)
select e.id,e.company_id,md5((to_jsonb(e)-'id'-'captured_at')::text),'baseline_observed_now',to_jsonb(e)
from public.earnings_events e on conflict(event_id,fingerprint) do nothing;

-- Deduplicate unchanged consecutive observations, while still recording a
-- revision that restores an older value (A -> B -> A).
create or replace function public.capture_financial_metric_version()
returns trigger language plpgsql security invoker set search_path='' as $$
declare hash text; previous_hash text;
begin
 hash=md5((to_jsonb(new)-'id'-'captured_at')::text);
 select split_part(fingerprint,':',1) into previous_hash from public.financial_metric_versions
 where company_id=new.company_id and period_end=new.period_end and period_type=new.period_type
 order by observed_at desc,id desc limit 1;
 if previous_hash is distinct from hash then
  insert into public.financial_metric_versions(company_id,period_end,period_type,fingerprint,provenance,snapshot)
  values(new.company_id,new.period_end,new.period_type,hash||':'||gen_random_uuid()::text,'live_ingestion',to_jsonb(new));
 end if;
 return new;
end $$;
create or replace function public.capture_earnings_event_version()
returns trigger language plpgsql security invoker set search_path='' as $$
declare hash text; previous_hash text;
begin
 hash=md5((to_jsonb(new)-'id'-'captured_at')::text);
 select split_part(fingerprint,':',1) into previous_hash from public.earnings_event_versions
 where event_id=new.id order by observed_at desc,id desc limit 1;
 if previous_hash is distinct from hash then
  insert into public.earnings_event_versions(event_id,company_id,fingerprint,provenance,snapshot)
  values(new.id,new.company_id,hash||':'||gen_random_uuid()::text,'live_ingestion',to_jsonb(new));
 end if;
 return new;
end $$;

-- An article can relate to several companies. Deduplicate by provider record
-- per company, rather than forbidding attribution of the same URL elsewhere.
alter table public.news_events drop constraint if exists news_events_source_url_key;
create index if not exists news_events_company_url_idx on public.news_events(company_id,source_url);
