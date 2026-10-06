-- Read-only regression checks after applying sql/recommendation_cadence.sql.
do $$
declare sessions date[];
begin
 sessions=array['2026-10-09']::date[];
 assert public.recommendation_weekly_decision('2026-10-09','2026-10-10','2026-10-04',sessions)->>'status'='not_due',
  'Saturday must not publish';
 assert public.recommendation_weekly_decision('2026-10-09','2026-10-11','2026-10-06',sessions)->>'status'='due',
  'Next Sunday is due after the accidental Tuesday publication';
 assert public.recommendation_weekly_decision('2026-10-09','2026-10-11','2026-10-11',sessions)->>'status'='not_due',
  'A completed Sunday group, including cash, must block a second group';
 assert public.recommendation_weekly_decision('2026-10-09','2026-10-12','2026-10-04',sessions)->>'status'='not_due',
  'Monday updates or manual runs must not publish';
 assert public.recommendation_weekly_decision('2026-10-09','2026-10-11',null,sessions)->>'status'='due',
  'The first group can publish on Sunday';
 assert public.recommendation_weekly_decision('2026-10-02','2026-10-04','2026-10-04',array['2026-10-02']::date[])->>'status'='not_due',
  'Legacy Saturday freezes already cover their following Sunday';

 -- Good Friday closes the market: Thursday is the latest close. No fifth-session wait.
 sessions=array['2026-03-30','2026-03-31','2026-04-01','2026-04-02']::date[];
 assert public.recommendation_weekly_decision('2026-04-02','2026-04-05','2026-03-29',sessions)->>'status'='due',
  'A holiday week still publishes on Sunday using Thursday data';
 assert public.recommendation_weekly_decision('2026-04-02','2026-04-12','2026-04-05',sessions)->>'status'='market_session_unavailable',
  'A previous week market close must fail closed';
 assert public.recommendation_weekly_decision('2026-10-09','2026-10-11',null,array[]::date[])->>'status'='market_session_unavailable',
  'A missing benchmark calendar must fail closed';

 -- Israel Sunday begins on Saturday UTC, during both summer and winter time.
 assert timezone('Asia/Jerusalem','2026-07-04 21:30:00+00'::timestamptz)::date='2026-07-05'::date;
 assert timezone('Asia/Jerusalem','2026-10-31 22:30:00+00'::timestamptz)::date='2026-11-01'::date;
end $$;
