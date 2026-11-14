-- Session-aware independent noon SLA. US price data from the prior NYSE
-- trading day becomes due the next Israel morning. No new NYSE session is
-- due on Israel Sunday/Monday or the morning after an NYSE holiday.
create or replace function research_internal.is_nyse_trading_day(p_day date)
returns boolean language plpgsql immutable set search_path = '' as $$
declare
 y integer := extract(year from p_day)::integer;
 jan1 date := make_date(y,1,1);
 jan_mlk date; feb_presidents date; may_memorial date;
 sep_labor date; nov_thanksgiving date;
 juneteenth date := make_date(y,6,19);
 july_fourth date := make_date(y,7,4);
 christmas date := make_date(y,12,25);
 a integer; b integer; c integer; d integer; e integer; f integer;
 g integer; h integer; i integer; k integer; l integer; m integer;
 easter_month integer; easter_day integer; good_friday date;
begin
 if extract(isodow from p_day)::integer > 5 then return false; end if;
 jan_mlk := make_date(y,1,1) + ((8-extract(isodow from make_date(y,1,1))::integer)%7) + 14;
 feb_presidents := make_date(y,2,1) + ((8-extract(isodow from make_date(y,2,1))::integer)%7) + 14;
 may_memorial := make_date(y,5,31) - ((extract(isodow from make_date(y,5,31))::integer-1+7)%7);
 sep_labor := make_date(y,9,1) + ((8-extract(isodow from make_date(y,9,1))::integer)%7);
 nov_thanksgiving := make_date(y,11,1) + ((4-extract(isodow from make_date(y,11,1))::integer+7)%7)+21;
 -- Gregorian computus (same formula as app.market_calendar.easter_sunday).
 a:=y%19; b:=y/100; c:=y%100; d:=b/4; e:=b%4; f:=(b+8)/25;
 g:=(b-f+1)/3; h:=(19*a+b-d-g+15)%30; i:=c/4; k:=c%4;
 l:=(32+2*e+2*i-h-k)%7; m:=(a+11*h+22*l)/451;
 easter_month:=(h+l-7*m+114)/31;
 easter_day:=(h+l-7*m+114)%31+1;
 good_friday:=make_date(y,easter_month,easter_day)-2;
 if p_day = any(array[jan_mlk,feb_presidents,good_friday,may_memorial,
                       sep_labor,nov_thanksgiving]) then return false; end if;
 -- New Year's: unlike ordinary Saturday holidays, the NYSE does not close
 -- the preceding Dec 31 when Jan 1 is a Saturday.
 if p_day=jan1 or (extract(isodow from jan1)::integer=7 and p_day=jan1+1)
 then return false; end if;
 if y>=2022 and p_day = case extract(isodow from juneteenth)::integer
   when 6 then juneteenth-1 when 7 then juneteenth+1 else juneteenth end
 then return false; end if;
 if p_day = case extract(isodow from july_fourth)::integer
   when 6 then july_fourth-1 when 7 then july_fourth+1 else july_fourth end
 then return false; end if;
 if p_day = case extract(isodow from christmas)::integer
   when 6 then christmas-1 when 7 then christmas+1 else christmas end
 then return false; end if;
 if p_day=make_date(2025,1,9) then return false; end if;
 return true;
end $$;

revoke all on function research_internal.is_nyse_trading_day(date)
 from public, anon, authenticated;

create or replace function research_internal.check_daily_deadline(p_now timestamptz default now())
returns jsonb language plpgsql set search_path = '' as $$
declare
 local_day date; deadline timestamptz; first_run timestamptz;
 completed timestamptz; result jsonb;
begin
 local_day=(p_now at time zone 'Asia/Jerusalem')::date;
 deadline=(local_day+time '12:00') at time zone 'Asia/Jerusalem';
 if p_now<deadline then
  return jsonb_build_object('status','before_deadline');
 end if;
 if not research_internal.is_nyse_trading_day(local_day-1) then
  return jsonb_build_object('status','not_due','local_date',local_day,
    'reason','No new completed NYSE session since the previous Israel noon');
 end if;
 perform pg_advisory_xact_lock(hashtextextended('daily-deadline:'||local_day::text,0));
 select metadata into result from public.pipeline_runs
 where pipeline='independent_daily_deadline' and expected_market_date=local_day limit 1;
 if found then return result; end if;
 select min(started_at),
        min(finished_at) filter(where status='success' and finished_at<=deadline)
 into first_run,completed from public.pipeline_runs
 where pipeline='daily_market_research'
   and (started_at at time zone 'Asia/Jerusalem')::date=local_day;
 result=jsonb_build_object('local_date',local_day,'deadline',deadline,
   'on_time',completed is not null,'first_started_at',first_run,
   'completed_by_deadline',completed,'monitor_provider','supabase_cron',
   'checked_at',p_now);
 insert into public.pipeline_runs(pipeline,status,started_at,finished_at,
   expected_market_date,metadata,error_message)
 values('independent_daily_deadline',
   case when completed is not null then 'success' else 'error' end,
   p_now,p_now,local_day,result,
   case when completed is null
     then 'No successful daily market refresh by 12:00 Asia/Jerusalem'
     else null end);
 return result;
end $$;

-- Existing execute permissions for the independent checker are unchanged.
