import json
from contextlib import contextmanager,closing
from datetime import date,timedelta
from types import SimpleNamespace

import pytest

from app.db.market_history import (MarketArchive,HistoryClient,cutoff_for,
                                  configure_history_client,require_full_history)
from scripts.archive_market_history import prune,connection

POLICY={"enabled":True,"id":1,"price_days":400,"feature_days":1100}


class RemoteQuery:
    def __init__(self,db,table):
        self.db=db; self.table=table; self.filters=[]; self.orders=[]; self.bounds=(0,999)
        self.columns="*"; self.payload=None
    def select(self,cols="*"): self.columns=cols; return self
    def eq(self,k,v): self.filters.append((k,"eq",v)); return self
    def gte(self,k,v): self.filters.append((k,"gte",v)); return self
    def order(self,k,desc=False): self.orders.append((k,desc)); return self
    def range(self,a,b): self.bounds=(a,b); return self
    def limit(self,n): self.bounds=(0,n-1); return self
    def upsert(self,rows,**kwargs): self.payload=rows; return self
    def execute(self):
        self.db.calls.append((self.table,self.columns,self.filters[:],self.bounds,self.payload))
        if self.payload is not None:
            self.db.written.extend(self.payload); return SimpleNamespace(data=self.payload)
        rows=self.db.rows.get(self.table,[])[:]
        for k,op,v in self.filters:
            rows=[r for r in rows if (r.get(k)==v if op=="eq" else r.get(k)>=v)]
        for k,desc in reversed(self.orders): rows.sort(key=lambda r:r.get(k,""),reverse=desc)
        a,b=self.bounds; rows=rows[a:b+1]
        if self.columns!="*": rows=[{k:r.get(k) for k in self.columns.split(",")} for r in rows]
        return SimpleNamespace(data=rows)


class Remote:
    def __init__(self,rows): self.rows=rows; self.calls=[]; self.written=[]
    def table(self,name): return RemoteQuery(self,name)


@pytest.fixture
def archive(tmp_path):
    result=MarketArchive(tmp_path/"history.sqlite3",create=True)
    result.set_metadata("project_ref","example")
    result.set_metadata("verified_export",{"sha256":"fixture"})
    return result


def test_full_history_combines_local_rows_current_cloud_and_provider_sources(archive):
    today=date.today().isoformat()
    rows=[{"id":1,"company_id":1,"price_date":"2020-01-01","source":"fmp","close":10},
          {"id":2,"company_id":1,"price_date":today,"source":"fmp","close":11},
          {"id":3,"company_id":1,"price_date":today,"source":"twelvedata","close":12}]
    archive.put_rows("price_history",rows[:2])
    remote=Remote({"price_history":rows[1:]})
    db=HistoryClient(remote,POLICY,archive)
    query=db.table("price_history").select("price_date,close,source").eq("company_id",1).order("price_date").order("source")
    first=query.range(0,1).execute().data
    second=query.range(2,3).execute().data
    assert [r["close"] for r in first+second]==[10,11,12]
    assert len(remote.calls)==1  # Cloud refresh is reused across archive pages.
    assert remote.calls[0][1]=="*"  # Never replace a full archived row with partial columns.


def test_old_writes_stay_local_and_recent_writes_reach_cloud(archive):
    remote=Remote({}); db=HistoryClient(remote,POLICY,archive)
    old={"company_id":2,"feature_date":"2020-01-01","close":1,"forward_up_5d":True}
    current={**old,"feature_date":date.today().isoformat(),"close":2}
    db.table("price_features").upsert([old,current],on_conflict="company_id,feature_date").execute()
    assert remote.written==[current]
    assert db.table("price_features").select("*").eq("company_id",2).eq("feature_date","2020-01-01").execute().data==[old]
    with pytest.raises(RuntimeError,match="unarchived write"):
        HistoryClient(Remote({}),POLICY).table("price_features").upsert([old]).execute()


def test_partial_updates_preserve_metadata_and_ignore_duplicates(archive):
    row={"id":91,"company_id":1,"price_date":"2020-01-01","source":"fmp","close":10,"captured_at":"original"}
    archive.put_rows("price_history",[row])
    archive.put_rows("price_history",[{**row,"close":99}],ignore_duplicates=True)
    archive.put_rows("price_history",[{"company_id":1,"price_date":"2020-01-01","source":"fmp","close":11}])
    db=HistoryClient(Remote({}),POLICY,archive)
    assert db.table("price_history").select("*").eq("company_id",1).execute().data==[{**row,"close":11}]


def test_backup_round_trip_and_tamper_detection(archive,tmp_path):
    payload='{"id":1,"company_id":1,"feature_date":"2020-01-01","close":10.1234567890123456789}'
    archive.put_raw("price_features",[payload])
    expected=archive.backup_verified(tmp_path/"backup.sqlite3")
    assert MarketArchive(tmp_path/"backup.sqlite3").fingerprint()==expected
    with closing(archive.connect()) as conn,conn:
        conn.execute("UPDATE market_rows SET payload=replace(payload,'2020','2021')")
    with pytest.raises(RuntimeError,match="checksum mismatch"): archive.fingerprint()


def test_missing_or_wrong_project_archive_never_falls_back(monkeypatch,archive,tmp_path):
    remote=Remote({"market_history_storage":[POLICY]})
    monkeypatch.setenv("LOCAL_MARKET_ARCHIVE",str(tmp_path/"missing.sqlite3"))
    with pytest.raises(RuntimeError,match="missing"): configure_history_client(remote,"https://example.supabase.co")
    monkeypatch.setenv("LOCAL_MARKET_ARCHIVE",str(archive.path))
    with pytest.raises(RuntimeError,match="different"): configure_history_client(remote,"https://other.supabase.co")


def test_cloud_cannot_train_on_silently_shortened_history():
    db=HistoryClient(Remote({}),POLICY)
    with pytest.raises(RuntimeError,match="Full-history"): require_full_history(db)
    with pytest.raises(RuntimeError,match="Unbounded"):
        db.table("price_features").select("*").order("feature_date").range(0,999).execute()
    # The existing daily setup window remains supported.
    assert db.table("price_features").select("feature_date").eq("company_id",1).order("feature_date",desc=True).limit(750).execute().data==[]


class PgResult:
    def __init__(self,rows=(),rowcount=0): self.rows=rows; self.rowcount=rowcount
    def fetchall(self): return self.rows


class PgCursor:
    def __init__(self,db,name=""): self.db=db; self.name=name; self.offset=0
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,query,params):
        self.table="price_history" if "price_history" in query.as_string() else "price_features"
    def fetchmany(self,n):
        if self.offset: return []
        self.offset+=1; return self.db.rows.get(self.table,[])
    @contextmanager
    def copy(self,query): yield self
    def write_row(self,row): self.db.keys.append(row)


class Pg:
    def __init__(self,rows,fail_second_delete=False):
        self.rows=rows; self.keys=[]; self.deletes=[]; self.activated=False; self.fail_second_delete=fail_second_delete
    def cursor(self,name=""): return PgCursor(self,name)
    @contextmanager
    def transaction(self):
        try: yield
        except Exception:
            self.deletes=[]; self.activated=False; raise
    def execute(self,query,params=()):
        text=query if isinstance(query,str) else query.as_string()
        if text.startswith("SELECT conname"): return PgResult()
        if text.startswith("UPDATE public.market_history_storage"): self.activated=True
        if text.startswith("DELETE"):
            table=params[0]; self.deletes.append(table)
            count=len(self.rows.get(table,[]))
            if self.fail_second_delete and table=="price_features": count+=1
            return PgResult(rowcount=count)
        return PgResult()


def prune_fixture(archive,tmp_path):
    data={}
    for table,column in (("price_history","price_date"),("price_features","feature_date")):
        row={"id":1,"company_id":1,column:"2020-01-01","close":10}
        if table=="price_history": row["source"]="twelvedata"
        raw=json.dumps(row); archive.put_raw(table,[raw]); data[table]=[(1,raw)]
    backup=tmp_path/"backup.sqlite3"; archive.backup_verified(backup)
    return data,backup


def test_prune_verifies_both_tables_before_deleting_any(archive,tmp_path):
    rows,backup=prune_fixture(archive,tmp_path)
    rows["price_features"]=[(1,rows["price_features"][0][1].replace('10','11'))]
    db=Pg(rows)
    with pytest.raises(RuntimeError,match="Source changed"): prune(db,archive,backup,POLICY)
    assert not db.deletes and not db.activated


def test_missing_backup_row_prevents_deletion(archive,tmp_path):
    rows,backup=prune_fixture(archive,tmp_path)
    with closing(MarketArchive(backup).connect()) as conn,conn:
        conn.execute("DELETE FROM market_rows WHERE table_name='price_features'")
    db=Pg(rows)
    with pytest.raises(RuntimeError,match="incomplete"): prune(db,archive,backup,POLICY)
    assert not db.deletes and not db.activated


def test_second_delete_failure_rolls_back_policy_and_first_delete(archive,tmp_path):
    rows,backup=prune_fixture(archive,tmp_path)
    db=Pg(rows,fail_second_delete=True)
    with pytest.raises(RuntimeError,match="count mismatch"): prune(db,archive,backup,POLICY)
    assert not db.deletes and not db.activated


def test_verified_prune_reports_exact_counts(archive,tmp_path):
    rows,backup=prune_fixture(archive,tmp_path)
    db=Pg(rows); report=prune(db,archive,backup,POLICY)
    assert report["price_history"]["deleted_rows"]==report["price_features"]["deleted_rows"]==1
    assert db.activated and len(db.keys)==2


def test_migration_requires_local_connection_without_exposing_a_password(monkeypatch):
    monkeypatch.delenv("SUPABASE_DB_URL",raising=False)
    with pytest.raises(RuntimeError,match="Set SUPABASE_DB_URL"): connection()
    monkeypatch.setenv("SUPABASE_URL","https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_DB_URL","postgresql://postgres.wrong:secret@pooler.supabase.com:5432/postgres")
    with pytest.raises(RuntimeError,match="same project") as error: connection()
    assert "secret" not in str(error.value)
