"""Local market archive and bounded cloud history, without changing callers' queries."""
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TABLE_DATES={"price_history":"price_date", "price_features":"feature_date"}
DEFAULT_DAYS={"price_history":400, "price_features":1100}


def project_ref(url):
    host=urlparse(url).hostname or ""
    if not host.endswith(".supabase.co"):
        raise ValueError("Use the project's standard SUPABASE_URL for archive identity")
    return host.split(".")[0]


class MarketArchive:
    def __init__(self,path,create=False):
        self.path=Path(path).expanduser().resolve()
        if not create and not self.path.is_file():
            raise RuntimeError("Local market archive is missing; run archive_market_history.py first")
        if create:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with closing(self.connect()) as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS archive_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS market_rows (
                      table_name TEXT NOT NULL, company_id INTEGER NOT NULL, trade_date TEXT NOT NULL,
                      source TEXT NOT NULL, payload TEXT NOT NULL, digest TEXT NOT NULL,
                      PRIMARY KEY(table_name,company_id,trade_date,source));
                    CREATE INDEX IF NOT EXISTS market_rows_date ON market_rows(table_name,trade_date,company_id);
                """)

    def connect(self):
        conn=sqlite3.connect(str(self.path),timeout=60)
        conn.execute("PRAGMA busy_timeout=60000")
        return conn

    def metadata(self,key):
        with closing(self.connect()) as conn:
            row=conn.execute("SELECT value FROM archive_metadata WHERE key=?",(key,)).fetchone()
        return json.loads(row[0]) if row else None

    def set_metadata(self,key,value):
        with closing(self.connect()) as conn,conn:
            conn.execute("INSERT OR REPLACE INTO archive_metadata VALUES (?,?)",(key,json.dumps(value)))

    def require_verified(self,ref):
        if self.metadata("project_ref")!=ref or not self.metadata("verified_export"):
            raise RuntimeError("Archive is unverified or belongs to a different Supabase project")

    @staticmethod
    def packed(table,payload):
        row=json.loads(payload)
        return (table,int(row["company_id"]),row[TABLE_DATES[table]],row.get("source") or "",payload,
                hashlib.md5(payload.encode()).hexdigest())

    def put_raw(self,table,payloads):
        with closing(self.connect()) as conn,conn:
            conn.executemany("INSERT OR REPLACE INTO market_rows VALUES (?,?,?,?,?,?)",
                             (self.packed(table,p) for p in payloads))

    def put_rows(self,table,rows,ignore_duplicates=False):
        # API upserts can omit server defaults. Preserve every other archived field.
        with closing(self.connect()) as conn,conn:
            for row in rows:
                key=(table,int(row["company_id"]),row[TABLE_DATES[table]],row.get("source") or "")
                old=conn.execute("SELECT payload FROM market_rows WHERE table_name=? AND company_id=? AND trade_date=? AND source=?",key).fetchone()
                if old and ignore_duplicates: continue
                merged={**(json.loads(old[0]) if old else {}),**row}
                payload=json.dumps(merged,sort_keys=True,separators=(",",":"),allow_nan=False)
                conn.execute("INSERT OR REPLACE INTO market_rows VALUES (?,?,?,?,?,?)",self.packed(table,payload))

    def latest(self,table,cid):
        with closing(self.connect()) as conn:
            row=conn.execute("SELECT max(trade_date) FROM market_rows WHERE table_name=? AND company_id=?",(table,cid)).fetchone()
        return row[0]

    def fingerprint(self):
        digest=hashlib.sha256(); counts={t:0 for t in TABLE_DATES}
        with closing(self.connect()) as conn:
            if conn.execute("PRAGMA quick_check").fetchone()[0]!="ok":
                raise RuntimeError("Archive integrity check failed")
            for table,payload,checksum in conn.execute("SELECT table_name,payload,digest FROM market_rows ORDER BY table_name,company_id,trade_date,source"):
                if hashlib.md5(payload.encode()).hexdigest()!=checksum:
                    raise RuntimeError("Archived row checksum mismatch; cloud data will not be deleted")
                digest.update(table.encode()+b"\0"+payload.encode()+b"\n")
                counts[table]+=1
        return {"counts":counts,"sha256":digest.hexdigest()}

    def backup_verified(self,path):
        backup=Path(path).expanduser().resolve()
        if backup==self.path or (backup.exists() and backup.samefile(self.path)):
            raise ValueError("Backup must be a separate file")
        backup.parent.mkdir(parents=True,exist_ok=True)
        with closing(self.connect()) as source,closing(sqlite3.connect(str(backup))) as target:
            source.backup(target)
        result=self.fingerprint()
        copy=MarketArchive(backup)
        if copy.fingerprint()!=result or copy.metadata("project_ref")!=self.metadata("project_ref"):
            raise RuntimeError("Backup verification failed; cloud data will not be deleted")
        return result


def load_storage_policy(db):
    try:
        rows=db.table("market_history_storage").select("*").eq("id",1).execute().data or []
    except Exception as exc:
        # Older installations have no policy table. Never hide quota/auth failures.
        if getattr(exc,"code",None) in ("PGRST205","42P01"):
            return None
        raise
    return rows[0] if rows and rows[0].get("enabled") else None


def cutoff_for(policy,table,today=None):
    days=policy["price_days" if table=="price_history" else "feature_days"]
    return ((today or datetime.now(ZoneInfo("Asia/Jerusalem")).date())-timedelta(days=days)).isoformat()


class HistoryClient:
    def __init__(self,remote,policy,archive=None):
        self.remote=remote; self.history_policy=policy; self.archive=archive
        self.synced=set()

    def __getattr__(self,name):
        return getattr(self.remote,name)

    def table(self,name):
        return HistoryQuery(self,name) if name in TABLE_DATES else self.remote.table(name)

    def sync_company(self,table,cid):
        key=(table,cid)
        if key in self.synced:
            return
        latest=self.archive.latest(table,cid)
        floor=cutoff_for(self.history_policy,table)
        # Re-read the label-maturation / gap-repair window, or the missed period.
        since=max(floor,(date.fromisoformat(latest)-timedelta(days=90)).isoformat()) if latest else floor
        column=TABLE_DATES[table]; start=0
        while True:
            q=self.remote.table(table).select("*").eq("company_id",cid).gte(column,since).order(column)
            if table=="price_history": q=q.order("source")
            rows=q.range(start,start+999).execute().data or []
            self.archive.put_rows(table,rows)
            if len(rows)<1000: break
            start+=1000
        self.synced.add(key)


class HistoryQuery:
    """The small PostgREST query subset used by the two market-history tables."""
    def __init__(self,client,table):
        self.client=client; self.name=table; self.calls=[]; self.columns="*"; self.filters=[]
        self.orders=[]; self.start=0; self.end=999; self.write=None; self.single_row=False

    def select(self,columns="*",**kwargs):
        self.columns=columns; self.calls.append(("select",(columns,),kwargs)); return self

    def _filter(self,op,column,value):
        self.filters.append((op,column,value)); self.calls.append((op,(column,value),{})); return self

    def eq(self,c,v): return self._filter("eq",c,v)
    def neq(self,c,v): return self._filter("neq",c,v)
    def gt(self,c,v): return self._filter("gt",c,v)
    def gte(self,c,v): return self._filter("gte",c,v)
    def lt(self,c,v): return self._filter("lt",c,v)
    def lte(self,c,v): return self._filter("lte",c,v)
    def in_(self,c,v): return self._filter("in_",c,v)

    def order(self,column,desc=False,**kwargs):
        self.orders.append((column,desc)); self.calls.append(("order",(column,),{"desc":desc,**kwargs})); return self

    def range(self,start,end):
        self.start=start; self.end=end; self.calls.append(("range",(start,end),{})); return self

    def limit(self,count):
        self.start=0; self.end=count-1; self.calls.append(("limit",(count,),{})); return self

    def single(self):
        self.single_row=True; self.calls.append(("single",(),{})); return self

    def upsert(self,rows,**kwargs):
        self.write=(rows,kwargs); return self

    @staticmethod
    def expression(column):
        if column=="company_id": return "company_id"
        if column in ("feature_date","price_date"): return "trade_date"
        if column=="source": return "source"
        if not re.fullmatch(r"[a-z_][a-z_0-9]*",column):
            raise ValueError("Unsupported archive column")
        return "json_extract(payload,'$."+column+"')"

    def execute(self):
        c=self.client; floor=cutoff_for(c.history_policy,self.name)
        if self.write is not None:
            payload,kwargs=self.write; rows=payload if isinstance(payload,list) else [payload]
            old=[r for r in rows if r[TABLE_DATES[self.name]]<floor]
            if old and not c.archive:
                raise RuntimeError("Old history requires LOCAL_MARKET_ARCHIVE; cloud retention will not discard an unarchived write")
            if c.archive: c.archive.put_rows(self.name,rows,ignore_duplicates=kwargs.get("ignore_duplicates",False))
            retained=[r for r in rows if r[TABLE_DATES[self.name]]>=floor]
            if not retained: return SimpleNamespace(data=rows)
            result=c.remote.table(self.name).upsert(retained,**kwargs).execute()
            if c.archive and result.data: c.archive.put_rows(self.name,result.data)
            return result
        if not c.archive:
            bounded=False
            for op,column,value in self.filters:
                if column==TABLE_DATES[self.name] and op in ("eq","gt","gte","lt","lte") and str(value)<floor:
                    raise RuntimeError("Requested history is archived locally; set LOCAL_MARKET_ARCHIVE on this computer")
                if column==TABLE_DATES[self.name] and op in ("eq","gt","gte"): bounded=True
            recent_limit=750 if self.name=="price_features" else 100
            recent=(TABLE_DATES[self.name],True) in self.orders and self.end<recent_limit
            if not bounded and not recent:
                raise RuntimeError("Unbounded historical reads require LOCAL_MARKET_ARCHIVE; cloud history is intentionally shorter")
            q=c.remote.table(self.name)
            for name,args,kwargs in self.calls: q=getattr(q,name)(*args,**kwargs)
            return q.execute()
        ids=None
        for op,column,value in self.filters:
            if column=="company_id" and op in ("eq","in_"):
                ids=[value] if op=="eq" else value
        if ids is None:
            ids=[r["id"] for r in c.remote.table("companies").select("id").execute().data or []]
        for cid in ids: c.sync_company(self.name,cid)
        where=["table_name=?"]; params=[self.name]
        ops={"eq":"=","neq":"!=","gt":">","gte":">=","lt":"<","lte":"<="}
        for op,column,value in self.filters:
            expr=self.expression(column)
            if op=="in_":
                where.append(expr+" IN ("+",".join("?" for _ in value)+")"); params.extend(value)
            else:
                where.append(expr+ops[op]+"?"); params.append(value)
        order=",".join(self.expression(column)+( " DESC" if desc else " ASC") for column,desc in self.orders)
        sql="SELECT payload FROM market_rows WHERE "+" AND ".join(where)
        if order: sql+=" ORDER BY "+order
        sql+=" LIMIT ? OFFSET ?"; params.extend((max(0,self.end-self.start+1),self.start))
        with closing(c.archive.connect()) as conn:
            rows=[json.loads(r[0]) for r in conn.execute(sql,params)]
        if self.columns!="*":
            columns=self.columns.split(",")
            for column in columns: self.expression(column)
            rows=[{column:row.get(column) for column in columns} for row in rows]
        if self.single_row:
            if len(rows)!=1: raise RuntimeError("Expected one archived market row")
            return SimpleNamespace(data=rows[0])
        return SimpleNamespace(data=rows)


def configure_history_client(remote,url):
    policy=load_storage_policy(remote)
    if not policy: return remote
    archive=None
    if os.getenv("LOCAL_MARKET_ARCHIVE"):
        archive=MarketArchive(os.environ["LOCAL_MARKET_ARCHIVE"])
        archive.require_verified(project_ref(url))
    return HistoryClient(remote,policy,archive)


def require_full_history(db):
    if getattr(db,"history_policy",None) and not getattr(db,"archive",None):
        raise RuntimeError("Full-history research runs on the archive computer. Configure LOCAL_MARKET_ARCHIVE; cloud data is intentionally bounded.")
