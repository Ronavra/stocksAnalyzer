"""Permissions, immutable snapshots and quota/lease arbitration on disposable CI DB."""
import os
from pathlib import Path
import pytest
import psycopg

DSN=os.getenv('TEST_ARCHIVE_PG_DSN')
pytestmark=pytest.mark.skipif(not DSN,reason='Disposable archive_test Postgres required')


def test_free_calendar_observations_and_one_daily_alpha_request():
    with psycopg.connect(DSN) as conn:
        assert conn.execute('select current_database()').fetchone()[0]=='archive_test'
        conn.execute('''DO $$ BEGIN
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN; END IF;
        END $$;
        CREATE TABLE IF NOT EXISTS public.companies(id bigint primary key);
        CREATE TABLE IF NOT EXISTS public.pipeline_runs(id bigint generated always as identity primary key,
          pipeline text,status text,started_at timestamptz,finished_at timestamptz,error_message text,metadata jsonb);''')
        conn.execute((Path(__file__).resolve().parents[1]/'sql/free_earnings.sql').read_text())
        conn.execute('insert into public.companies(id) values(987654321)')
        conn.execute("""insert into public.earnings_calendar_snapshots(company_id,source,observed_at,status,dates,source_url)
          values(987654321,'yahoo_finance',now()-interval '1 hour','observed','["2026-12-01"]','https://finance.yahoo.com/'),
                (987654321,'yahoo_finance',now(),'unknown','[]','https://finance.yahoo.com/'),
                (987654321,'alphavantage',now()+interval '1 hour','observed','["2026-12-01"]','https://www.alphavantage.co/')""")
        rows=conn.execute('select public.free_earnings_calendar(array[987654321]::bigint[])').fetchone()[0]
        assert len(rows)==1 and rows[0]['status']=='unknown'
        assert conn.execute('select public.claim_alpha_earnings_calendar()').fetchone()[0]
        assert not conn.execute('select public.claim_alpha_earnings_calendar()').fetchone()[0]
        claim=conn.execute('select public.claim_free_earnings_refresh()').fetchone()[0]
        assert claim['run']
        assert not conn.execute('select public.claim_free_earnings_refresh()').fetchone()[0]['run']
        conn.execute("update public.pipeline_runs set started_at=now()-interval '2 hours' where id=%s",(claim['id'],))
        assert conn.execute('select public.claim_free_earnings_refresh()').fetchone()[0]['run']
        assert not conn.execute("select has_function_privilege('anon','public.free_earnings_calendar(bigint[])','execute')").fetchone()[0]
        assert not conn.execute("select has_table_privilege('service_role','public.earnings_calendar_snapshots','update')").fetchone()[0]
        conn.rollback()
