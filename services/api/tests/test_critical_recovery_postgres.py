"""Atomic replacement and lease recovery on CI's disposable Postgres only."""
import json
import os
from datetime import date, timedelta
from pathlib import Path
import psycopg
import pytest

DSN=os.getenv("TEST_ARCHIVE_PG_DSN")
pytestmark=pytest.mark.skipif(not DSN,reason="Disposable archive_test Postgres required")
SQL=Path(__file__).resolve().parents[1]/"sql"

@pytest.fixture
def pg():
    with psycopg.connect(DSN) as conn:
        assert conn.execute("select current_database()").fetchone()[0]=="archive_test"
        conn.execute("""DO $$ BEGIN
         IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='anon') THEN CREATE ROLE anon NOLOGIN; END IF;
         IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
         IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='service_role') THEN CREATE ROLE service_role NOLOGIN; END IF;
        END $$;
        CREATE TABLE IF NOT EXISTS public.companies(id bigint primary key,ticker text);
        CREATE TABLE IF NOT EXISTS public.price_history(company_id bigint,price_date date,close numeric,source text);
        CREATE TABLE IF NOT EXISTS public.pipeline_runs(id bigint generated always as identity primary key,
         pipeline text,status text,started_at timestamptz default now(),finished_at timestamptz,
         error_message text,metadata jsonb default '{}');
        """)
        conn.execute((SQL/'research_predictions.sql').read_text())
        conn.execute("""ALTER TABLE public.research_predictions
         ADD COLUMN IF NOT EXISTS model_probability_up numeric,
         ADD COLUMN IF NOT EXISTS model_expected_return numeric,
         ADD COLUMN IF NOT EXISTS model_calibration_brier numeric,
         ADD COLUMN IF NOT EXISTS model_baseline_brier numeric,
         ADD COLUMN IF NOT EXISTS model_feature_coverage numeric,
         ADD COLUMN IF NOT EXISTS model_diagnostics jsonb;
        """)
        conn.execute((SQL/'research_reliability.sql').read_text().split('-- Register complete legacy')[0])
        conn.execute((SQL/'critical_weekly_recovery.sql').read_text())
        conn.execute((SQL/'daily_refresh_lease.sql').read_text())
        conn.execute("TRUNCATE public.research_predictions,public.recommendation_cohorts,public.recommendation_revisions,public.pipeline_runs,public.price_history")
        conn.execute("INSERT INTO public.companies(id,ticker) VALUES(9001,'SPY'),(9002,'TEST') ON CONFLICT(id) DO UPDATE SET ticker=excluded.ticker")
        yield conn
        conn.rollback()


def cohort(pg):
    day=date.today()-timedelta(days=2)
    pg.execute("INSERT INTO public.price_history(company_id,price_date,close,source) VALUES(9001,%s,100,'test')",(day,))
    stamp=pg.execute("INSERT INTO public.recommendation_cohorts(signal_date,model_version,horizons,expected_picks,status) VALUES(%s,'old',ARRAY[5,10,20],1,'published') RETURNING published_at",(day,)).fetchone()[0]
    for h in (5,10,20):
        pg.execute("INSERT INTO public.research_predictions(company_id,signal_date,horizon_days,signal,rank,model_version) VALUES(9002,%s,%s,'UP',1,'old')",(day,h))
    return day,stamp


def replace(pg,day,stamp,company=9002,version='new',predictions=None):
    records=predictions if predictions is not None else [dict(company_id=company,signal_date=day.isoformat(),horizon_days=h,signal='UP',rank=1,model_version=version) for h in (5,10,20)]
    return pg.execute("SELECT public.replace_recommendation_cohort(%s,%s,ARRAY[5,10,20],%s::jsonb,'{}'::jsonb,'old',%s,'Correct official revenue sources')",(day,version,json.dumps(records),stamp)).fetchone()[0]


def test_atomic_replacement_archives_old_rows_and_rejects_stale_retry(pg):
    day,stamp=cohort(pg)
    assert replace(pg,day,stamp)=={'status':'replaced','expected_picks':1,'rows':3}
    assert pg.execute("select count(*),min(model_version) from research_predictions").fetchone()==(3,'new')
    assert pg.execute("select jsonb_array_length(old_predictions),old_cohort->>'model_version' from recommendation_revisions").fetchone()==(3,'old')
    with pytest.raises(psycopg.Error,match='Publication changed'):
        with pg.transaction(): replace(pg,day,stamp)
    assert pg.execute("select count(*) from recommendation_revisions").fetchone()[0]==1


def test_failure_after_delete_rolls_back_entire_publication(pg):
    day,stamp=cohort(pg)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with pg.transaction(): replace(pg,day,stamp,company=999999)
    assert pg.execute("select count(*),min(model_version) from research_predictions").fetchone()==(3,'old')
    assert pg.execute("select model_version,published_at from recommendation_cohorts").fetchone()==('old',stamp)
    assert pg.execute("select count(*) from recommendation_revisions").fetchone()[0]==0


def test_entered_and_empty_cohorts_are_preserved(pg):
    day,stamp=cohort(pg)
    with pytest.raises(psycopg.Error,match='Empty replacement'):
        with pg.transaction(): replace(pg,day,stamp,predictions=[])
    pg.execute("update research_predictions set entry_price=100 where horizon_days=5")
    with pytest.raises(psycopg.Error,match='unevaluated'):
        with pg.transaction(): replace(pg,day,stamp)
    assert pg.execute("select count(*),min(model_version) from research_predictions").fetchone()==(3,'old')


def test_expiration_closes_yesterday_orphan_without_breaking_active_claim(pg):
    pg.execute("INSERT INTO pipeline_runs(pipeline,status,started_at,metadata) VALUES('daily_market_research','running',now()-interval '1 day','{\"stage\":\"prices\"}')")
    assert pg.execute("select expire_daily_market_refreshes()").fetchone()[0]==1
    assert pg.execute("select status,metadata->>'lease_expired',metadata->>'stage' from pipeline_runs").fetchone()==('error','true','prices')
    claim=pg.execute("select claim_daily_market_refresh(false)").fetchone()[0]
    assert claim['run']
    assert pg.execute("select claim_daily_market_refresh(true)").fetchone()[0]=={'run':False}
