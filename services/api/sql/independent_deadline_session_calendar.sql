-- Supabase's independent noon monitor currently checks every calendar day,
-- even when there is no new NYSE session. The NYSE closes on Saturday and
-- Sunday, so the prior day's close becomes due on Israel Tuesday-Saturday,
-- not Israel Sunday-Monday. Keep real Saturday checks for Friday's close.
--
-- This is deliberately only a weekend schedule fix. US exchange holidays
-- still require calendar-aware SQL parity with app.market_calendar; the
-- GitHub monitor already handles those via Python.
--
-- Running cron.schedule with an existing job name updates its schedule.
select cron.schedule(
  'stocks-analyzer-independent-deadline',
  '17 * * * 2-6',
  'select research_internal.check_daily_deadline();'
);
