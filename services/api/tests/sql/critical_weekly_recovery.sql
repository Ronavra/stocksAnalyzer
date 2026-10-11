-- Production-safe transaction test: all data changes are rolled back.
begin;
set local role service_role;
do $$
declare c public.recommendation_cohorts; records jsonb; result jsonb; old_count integer; archived integer;
begin
 select * into c from public.recommendation_cohorts order by signal_date desc limit 1;
 select count(*),jsonb_agg(to_jsonb(r)||jsonb_build_object('model_version','weekly-rollback-test'))
 into old_count,records from public.research_predictions r where signal_date=c.signal_date;
 select count(*) into archived from public.recommendation_revisions;
 begin
  perform public.replace_recommendation_cohort(c.signal_date,'weekly-rollback-test',c.horizons,'[]','{}',
    c.model_version,c.published_at,'Atomic replacement regression test');
  raise exception 'Empty replacement was accepted';
 exception when others then
  if sqlerrm not like 'Empty replacement refused%' then raise; end if;
 end;
 -- Force a real foreign-key failure after archive/delete, proving rollback.
 begin
  perform public.replace_recommendation_cohort(c.signal_date,'weekly-rollback-test',c.horizons,
    (select jsonb_agg(case when (r->>'rank')::int=1 then r||jsonb_build_object('company_id',9223372036854775807) else r end) from jsonb_array_elements(records) r),
    '{}',c.model_version,c.published_at,'Atomic replacement regression test');
  raise exception 'Foreign-key failure was not raised';
 exception when foreign_key_violation then null;
 end;
 if (select count(*) from public.research_predictions where signal_date=c.signal_date)<>old_count
    or (select count(*) from public.recommendation_revisions)<>archived then
  raise exception 'Failed replacement did not roll back';
 end if;
 result=public.replace_recommendation_cohort(c.signal_date,'weekly-rollback-test',c.horizons,records,'{}',
    c.model_version,c.published_at,'Atomic replacement regression test');
 if result->>'status'<>'replaced'
   or (select count(*) from public.research_predictions where signal_date=c.signal_date)<>old_count
   or (select count(*) from public.recommendation_revisions)<>archived+1 then
  raise exception 'Atomic replacement did not preserve complete horizons';
 end if;
 begin
  perform public.replace_recommendation_cohort(c.signal_date,'weekly-rollback-test',c.horizons,records,'{}',
    c.model_version,c.published_at,'Atomic replacement regression test');
  raise exception 'Stale concurrent retry was accepted';
 exception when others then
  if sqlerrm not like 'Publication changed%' then raise; end if;
 end;
end $$;
rollback;
select signal_date,model_version,expected_picks,
 (select count(*) from public.research_predictions p where p.signal_date=c.signal_date) as preserved_rows,
 (select count(*) from public.recommendation_revisions) as committed_revisions
from public.recommendation_cohorts c order by signal_date desc limit 1;
