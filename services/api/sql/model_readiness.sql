-- A global lease prevents a delayed worker from replacing a newer validation.
create or replace function public.claim_predictive_validation(p_model_version text,p_claim boolean default true)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v_id bigint;
begin
 perform pg_catalog.pg_advisory_xact_lock(73519248);
 update public.model_validation_runs set status='error',finished_at=now(),
  error_message='Validation interrupted: six-hour execution lease expired; no promotion.'
 where status='running' and started_at<now()-interval '6 hours';
 if not p_claim then return jsonb_build_object('run',false,'reason','reconciled'); end if;
 if p_model_version is null or length(p_model_version)=0 then raise exception 'Model version required'; end if;
 select id into v_id from public.model_validation_runs where status='running' order by started_at desc limit 1;
 if v_id is not null then return jsonb_build_object('run',false,'reason','already_running','id',v_id); end if;
 insert into public.model_validation_runs(status,model_version,started_at)
 values('running',p_model_version,now()) returning id into v_id;
 return jsonb_build_object('run',true,'id',v_id,'lease_hours',6);
end;
$$;
revoke all on function public.claim_predictive_validation(text,boolean) from public,anon,authenticated;
grant execute on function public.claim_predictive_validation(text,boolean) to service_role;

create or replace function public.claim_local_model_research()
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v_id bigint;
begin
 perform pg_catalog.pg_advisory_xact_lock(73519249);
 update public.pipeline_runs set status='error',finished_at=now(),error_message='Local research lease expired'
 where pipeline='local_model_validation' and status='running' and started_at<now()-interval '6 hours';
 select id into v_id from public.pipeline_runs where pipeline='local_model_validation' and status='running' limit 1;
 if v_id is not null then return jsonb_build_object('run',false,'id',v_id); end if;
 insert into public.pipeline_runs(pipeline,status,started_at) values('local_model_validation','running',now()) returning id into v_id;
 return jsonb_build_object('run',true,'id',v_id);
end;
$$;
revoke all on function public.claim_local_model_research() from public,anon,authenticated;
grant execute on function public.claim_local_model_research() to service_role;

create or replace function public.claim_financial_coverage_repair()
returns jsonb language plpgsql security invoker set search_path='' as $$
declare v_id bigint;
begin
 perform pg_catalog.pg_advisory_xact_lock(73519250);
 update public.pipeline_runs set status='error',finished_at=now(),error_message='Financial repair lease expired'
 where pipeline='financial_coverage_repair' and status='running' and started_at<now()-interval '1 hour';
 select id into v_id from public.pipeline_runs where pipeline='financial_coverage_repair' and status='running' limit 1;
 if v_id is not null then return jsonb_build_object('run',false,'id',v_id); end if;
 insert into public.pipeline_runs(pipeline,status,started_at) values('financial_coverage_repair','running',now()) returning id into v_id;
 return jsonb_build_object('run',true,'id',v_id);
end;
$$;
revoke all on function public.claim_financial_coverage_repair() from public,anon,authenticated;
grant execute on function public.claim_financial_coverage_repair() to service_role;

create or replace function public.research_model_readiness()
returns jsonb language sql stable security invoker set search_path='' as $$
 select jsonb_build_object(
 'history_requires_local_archive',coalesce((select enabled from public.market_history_storage where id=1),false),
 'archive_verified_at',(select archived_at from public.market_history_storage where id=1),
 'financial_observation_start',(select min(observed_at) from public.financial_metric_versions),
 'financial_observation_days',(select count(distinct observed_at::date) from public.financial_metric_versions),
 'estimate_observation_start',(select min(captured_at) from public.estimate_snapshots),
 'estimate_observation_days',(select count(distinct captured_date) from public.estimate_snapshots),
 'fiscal_estimate_companies',(select count(distinct e.company_id) from public.estimate_snapshots e
   join public.companies c on c.id=e.company_id and c.is_sp500
   where e.captured_at>=now()-interval '48 hours' and e.eps_consensus is not null and e.revenue_consensus is not null),
 'minimum_observed_sample_dates',26,'required_model_sample_dates',120,
 'membership_observation_start',(select min(captured_at) from public.index_memberships),
 'latest_execution',(select to_jsonb(r)-'id'-'error_message' from
   (select id,status,started_at,finished_at,metadata,error_message from public.pipeline_runs
    where pipeline='model_validation_execution' order by started_at desc,id desc limit 1)r),
 'latest_training',(select jsonb_build_object('id',id,'model_version',model_version,'started_at',started_at,
   'finished_at',finished_at,'status',case when status='running' and started_at<now()-interval '6 hours' then 'interrupted' else status end,
   'error_message',error_message,'best_stage',best_stage) from public.model_validation_runs
   where model_version like 'calibrated-multifactor-%' order by started_at desc,id desc limit 1),
 'validated_forecast',false);
$$;
revoke all on function public.research_model_readiness() from public,anon,authenticated;
grant execute on function public.research_model_readiness() to service_role;
