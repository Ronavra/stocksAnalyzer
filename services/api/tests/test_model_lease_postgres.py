"""Lease recovery on CI's disposable database; never on the hosted project."""
import os
from pathlib import Path
import psycopg
import pytest
DSN=os.getenv('TEST_ARCHIVE_PG_DSN')
pytestmark=pytest.mark.skipif(not DSN,reason='Disposable archive_test Postgres required')


def test_validation_claim_excludes_other_workers_and_recovers_expired_attempt():
    with psycopg.connect(DSN) as conn:
        assert conn.execute('select current_database()').fetchone()[0]=='archive_test'
        conn.execute('''DO $$ BEGIN
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
        IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN; END IF;
        END $$;
        CREATE TABLE public.model_validation_runs(id bigint generated always as identity primary key,
        status text,model_version text,started_at timestamptz,finished_at timestamptz,error_message text);''')
        # The predictive claim has no dependency on the coverage tables or local job claim.
        sql=(Path(__file__).resolve().parents[1]/'sql/model_readiness.sql').read_text()
        conn.execute(sql.split('create or replace function public.claim_local_model_research')[0])
        first=conn.execute("select public.claim_predictive_validation('test',true)").fetchone()[0]
        assert first['run']
        assert not conn.execute("select public.claim_predictive_validation('other',true)").fetchone()[0]['run']
        conn.execute("update public.model_validation_runs set started_at=now()-interval '7 hours'")
        second=conn.execute("select public.claim_predictive_validation('new',true)").fetchone()[0]
        assert second['run'] and second['id']!=first['id']
        assert conn.execute("update public.model_validation_runs set status='success' where id=%s and status='running' returning id",(first['id'],)).fetchall()==[]
        assert not conn.execute("select has_function_privilege('anon','public.claim_predictive_validation(text,boolean)','execute')").fetchone()[0]
        conn.rollback()
