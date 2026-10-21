"""Snapshot identity, CAS, service-only access and rollback in disposable CI DB."""
import os
import json
from pathlib import Path
import psycopg
import pytest
DSN=os.getenv('TEST_ARCHIVE_PG_DSN')
pytestmark=pytest.mark.skipif(not DSN,reason='Disposable archive_test Postgres required')


def test_atomic_portfolio_snapshots_and_permissions():
    with psycopg.connect(DSN) as conn:
        assert conn.execute('select current_database()').fetchone()[0]=='archive_test'
        conn.execute('''DO $$ BEGIN
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN; END IF;
        END $$;
        CREATE TABLE IF NOT EXISTS public.price_history(company_id bigint,price_date date,close numeric,source text);''')
        conn.execute((Path(__file__).resolve().parents[1]/'sql/active_portfolio.sql').read_text())
        today=conn.execute("select (now() at time zone 'America/New_York')::date").fetchone()[0].isoformat()
        p={'decision_day':today,'portfolio':{'policy':'active-ten-v1','mode':'paper','positions':[],
           'orders':[],'cash':100000,'validated':False,'as_of_date':today}}
        with conn.transaction():
            conn.execute('savepoint bad_revision')
            with pytest.raises(psycopg.Error,match='changed'):
                conn.execute('select public.record_active_portfolio(10,%s)',(json.dumps(p),))
            conn.execute('rollback to bad_revision')
        first=conn.execute('select public.record_active_portfolio(0,%s)',(json.dumps(p),)).fetchone()[0]
        assert first['status']=='recorded'
        again=conn.execute('select public.record_active_portfolio(0,%s)',(json.dumps(p),)).fetchone()[0]
        assert again['status']=='already_recorded' and first['revision']==again['revision']
        assert conn.execute('select count(*) from public.active_portfolio_snapshots').fetchone()[0]==1
        assert not conn.execute("select has_function_privilege('anon','public.record_active_portfolio(bigint,jsonb)','execute')").fetchone()[0]
        assert not conn.execute("select has_function_privilege('authenticated','public.active_portfolio_price_window(date,date,bigint[])','execute')").fetchone()[0]
        assert not conn.execute("select has_table_privilege('service_role','public.active_portfolio_snapshots','update')").fetchone()[0]
        conn.rollback()
