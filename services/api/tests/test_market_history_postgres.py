"""Archive/prune integration on CI's disposable Postgres, never on Supabase."""
import json
import os
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
import psycopg

from app.db.market_history import MarketArchive
from scripts.archive_market_history import export,prune,compact

DSN=os.getenv("TEST_ARCHIVE_PG_DSN")
pytestmark=pytest.mark.skipif(not DSN,reason="Disposable archive_test Postgres required")
POLICY={"enabled":True,"price_days":400,"feature_days":1100}


@pytest.fixture
def pg():
    with psycopg.connect(DSN,autocommit=True) as conn:
        # A misconfigured test environment must never touch a production DB.
        if conn.execute("SELECT current_database()").fetchone()[0]!="archive_test":
            pytest.fail("Integration database must be the disposable archive_test database")
        conn.execute("""DO $$ BEGIN
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN; END IF;
        END $$;
        CREATE TABLE IF NOT EXISTS public.price_history(
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,company_id bigint NOT NULL,
          price_date date NOT NULL,close numeric,source text NOT NULL,
          captured_at timestamptz DEFAULT now(),UNIQUE(company_id,price_date,source));
        CREATE TABLE IF NOT EXISTS public.price_features(
          id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,company_id bigint NOT NULL,
          feature_date date NOT NULL,close numeric,forward_return_5d numeric,
          created_at timestamptz DEFAULT now(),UNIQUE(company_id,feature_date));
        """)
        sql=(Path(__file__).resolve().parents[1]/"sql/local_market_history.sql").read_text()
        conn.execute(sql)
        conn.execute("UPDATE public.market_history_storage SET enabled=false WHERE id=1")
        conn.execute("TRUNCATE public.price_history,public.price_features RESTART IDENTITY")
        for day in ("2020-01-01","2020-01-02",date.today().isoformat()):
            conn.execute("INSERT INTO public.price_history(company_id,price_date,close,source) VALUES(1,%s,10.1234567890123456789,'twelvedata')",(day,))
            conn.execute("INSERT INTO public.price_features(company_id,feature_date,close,forward_return_5d) VALUES(1,%s,10.1234567890123456789,0.01234567890123456789)",(day,))
        yield conn


def backed_export(pg,tmp_path):
    archive=MarketArchive(tmp_path/"archive.sqlite3",create=True)
    archive.set_metadata("project_ref","example")
    report=export(pg,archive,POLICY,full=True)
    fingerprint=archive.fingerprint(); archive.set_metadata("verified_export",fingerprint)
    backup=tmp_path/"backup.sqlite3"; archive.backup_verified(backup)
    return archive,backup,report


def test_real_export_prune_compaction_and_service_role_retention(pg,tmp_path):
    archive,backup,exported=backed_export(pg,tmp_path)
    assert exported["price_history"]["exported_rows"]==exported["price_features"]["exported_rows"]==3
    with closing(archive.connect()) as local:
        payload=local.execute("SELECT payload FROM market_rows WHERE table_name='price_history' ORDER BY trade_date LIMIT 1").fetchone()[0]
    assert "10.1234567890123456789" in payload  # Raw numeric precision survives export.
    report=prune(pg,archive,backup,POLICY)
    assert report["price_history"]["deleted_rows"]==report["price_features"]["deleted_rows"]==2
    assert pg.execute("SELECT count(*) FROM public.price_history").fetchone()[0]==1
    assert pg.execute("SELECT count(*) FROM public.price_features").fetchone()[0]==1
    assert pg.execute("SELECT enabled FROM public.market_history_storage WHERE id=1").fetchone()[0]
    pg.execute("GRANT INSERT,SELECT ON public.price_history,public.price_features TO service_role")
    pg.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO service_role")
    pg.execute("SET ROLE service_role")
    try:
        pg.execute("INSERT INTO public.price_history(company_id,price_date,close,source) VALUES(2,current_date,20,'test')")
        with pytest.raises(psycopg.errors.RaiseException,match="History older"):
            pg.execute("INSERT INTO public.price_features(company_id,feature_date,close) VALUES(2,'2020-01-01',20)")
    finally: pg.execute("RESET ROLE")
    compact(pg)
    assert archive.fingerprint()==MarketArchive(backup).fingerprint()


def test_real_changed_source_aborts_without_any_cloud_deletion(pg,tmp_path):
    archive,backup,_=backed_export(pg,tmp_path)
    pg.execute("UPDATE public.price_features SET close=99 WHERE feature_date='2020-01-01'")
    with pytest.raises(RuntimeError,match="Source changed"): prune(pg,archive,backup,POLICY)
    assert pg.execute("SELECT count(*) FROM public.price_history").fetchone()[0]==3
    assert pg.execute("SELECT count(*) FROM public.price_features").fetchone()[0]==3
    assert not pg.execute("SELECT enabled FROM public.market_history_storage WHERE id=1").fetchone()[0]


def test_real_missing_backup_aborts_without_any_cloud_deletion(pg,tmp_path):
    archive,backup,_=backed_export(pg,tmp_path)
    with closing(MarketArchive(backup).connect()) as second,second:
        second.execute("DELETE FROM market_rows WHERE table_name='price_features' AND trade_date='2020-01-01'")
    with pytest.raises(RuntimeError,match="incomplete"): prune(pg,archive,backup,POLICY)
    assert pg.execute("SELECT count(*) FROM public.price_history").fetchone()[0]==3
    assert not pg.execute("SELECT enabled FROM public.market_history_storage WHERE id=1").fetchone()[0]
