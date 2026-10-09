"""Verified local export; cloud deletion is opt-in and exact-row checked.

Use a direct/session-pooler Postgres connection, not the restricted Data API.
No connection string or database password is printed or written to the archive.
"""
import argparse
import hashlib
import json
import os
import re
import sys
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import quote,quote_plus

from dotenv import load_dotenv,set_key

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/".env")
from app.db.market_history import MarketArchive,TABLE_DATES,DEFAULT_DAYS,cutoff_for,project_ref

CURRENT_STAGE="startup"


def progress(stage):
    global CURRENT_STAGE
    CURRENT_STAGE=stage
    print(f"Archive migration: {stage}",flush=True)


def safe_error(exc):
    """Keep the server/network reason without echoing credentials from libpq."""
    message=str(exc)
    dsn=os.getenv("SUPABASE_DB_URL","")
    secrets=[dsn,os.getenv("PGPASSWORD",""),os.getenv("SUPABASE_SERVICE_ROLE_KEY","")]
    if dsn:
        try:
            from psycopg.conninfo import conninfo_to_dict
            password=conninfo_to_dict(dsn).get("password","")
            secrets.extend((password,quote(password,safe=""),quote_plus(password)))
        except Exception: pass
    for secret in sorted(set(secrets),key=len,reverse=True):
        if secret: message=message.replace(secret,"[redacted]")
    message=re.sub(r"postgres(?:ql)?://[^\s]+","[redacted connection string]",message,flags=re.I)
    message=re.sub(r"\b(password|passwd|pwd)\s*=\s*(?:'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\"|[^\s,;]+)",r"\1=[redacted]",message,flags=re.I)
    return message[:2000]


def error_hint(exc):
    message=str(exc).lower(); code=getattr(exc,"sqlstate",None)
    if code=="28P01" or "password authentication failed" in message or "sasl authentication failed" in message:
        return "Use the database password in SUPABASE_DB_URL. Percent-encode reserved password characters; the Supabase account login password is different."
    if "tenant or user not found" in message:
        return "Copy the complete Session pooler URI again, including its host and postgres.PROJECT-REF username."
    if "network is unreachable" in message or "no route to host" in message:
        return "Use Dashboard > Connect > Session pooler on port 5432; a direct IPv6 connection may be unreachable from this computer."
    if "could not translate host name" in message or "name or service not known" in message or "getaddrinfo" in message:
        return "Check the pooler hostname in SUPABASE_DB_URL and this computer's DNS/network connection."
    if "timeout" in message or "timed out" in message or "connection refused" in message:
        return "Check the Session pooler host/port 5432 and network access to it. The --check-connection command makes no archive or cloud-data changes."
    return "Run archive_market_history.py --check-connection to isolate connection/access problems. Keep existing archive files."


def connection():
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    url=os.getenv("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("Set SUPABASE_DB_URL in services/api/.env using Dashboard > Connect > Session pooler. Keep the password out of chat.")
    if "[YOUR-PASSWORD]" in url:
        raise RuntimeError("Replace [YOUR-PASSWORD] in SUPABASE_DB_URL with the actual database password locally")
    ref=project_ref(os.environ.get("SUPABASE_URL",""))
    try: parts=conninfo_to_dict(url)
    except Exception: raise RuntimeError("Invalid SUPABASE_DB_URL; copy the Postgres URI from Dashboard > Connect") from None
    if ref not in (parts.get("host","")+" "+parts.get("user","")):
        raise RuntimeError("Postgres connection must identify the same project as SUPABASE_URL")
    # Session pooling supports named cursors; transaction pooling is unsuitable.
    if parts.get("port")=="6543":
        raise RuntimeError("Use the session pooler on port 5432, not the transaction pooler")
    conn=psycopg.connect(url,sslmode="require",connect_timeout=15,prepare_threshold=None)
    # Supabase documents a session-only write override for reducing oversized DBs.
    # This does not change the global read-only setting or the Data API quota.
    try:
        conn.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ WRITE")
        conn.commit()
    except Exception:
        conn.close()
        raise
    return conn


def export(conn,archive,policy,full):
    from psycopg import sql
    report={}
    with conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        for table,column in TABLE_DATES.items():
            where=sql.SQL("") if full else sql.SQL(" WHERE {} < %s").format(sql.Identifier(column))
            query=sql.SQL("SELECT to_jsonb(t)::text FROM public.{} t{}").format(sql.Identifier(table),where)
            params=() if full else (cutoff_for(policy,table),)
            count=0; digest=hashlib.sha256()
            with conn.cursor(name="archive_"+table) as cur:
                cur.execute(query,params)
                while True:
                    batch=cur.fetchmany(2000)
                    if not batch: break
                    payloads=[r[0] for r in batch]
                    archive.put_raw(table,payloads)
                    for payload in payloads: digest.update(payload.encode()+b"\n")
                    count+=len(batch)
                    if count%100000==0: print(f"Exported {table}: {count} rows",flush=True)
            # Counts are checked against the same immutable source snapshot.
            query=sql.SQL("SELECT count(*) FROM public.{}{}").format(sql.Identifier(table),where)
            expected=conn.execute(query,params).fetchone()[0]
            if count!=expected: raise RuntimeError("Source export count mismatch")
            report[table]={"exported_rows":count,"source_stream_sha256":digest.hexdigest(),
                           "cloud_cutoff":cutoff_for(policy,table)}
    return report


def prune(conn,archive,backup,policy):
    """Lock both source tables, verify every candidate in both files, then delete."""
    from psycopg import sql
    backup_archive=MarketArchive(backup)
    result={}
    with closing(archive.connect()) as local,closing(backup_archive.connect()) as second,conn.transaction():
        conn.execute("SET LOCAL lock_timeout='15s'")
        conn.execute("SET LOCAL statement_timeout='15min'")
        conn.execute("LOCK TABLE public.price_history,public.price_features IN SHARE ROW EXCLUSIVE MODE")
        dependencies=conn.execute("SELECT conname FROM pg_constraint WHERE contype='f' AND confrelid IN ('public.price_history'::regclass,'public.price_features'::regclass)").fetchall()
        if dependencies:
            raise RuntimeError("History rows have foreign-key dependents; automatic pruning refused")
        conn.execute("CREATE TEMP TABLE archived_delete_keys(table_name text,id bigint,digest text,PRIMARY KEY(table_name,id)) ON COMMIT DROP")
        for table,column in TABLE_DATES.items():
            query=sql.SQL("SELECT id,to_jsonb(t)::text FROM public.{} t WHERE {}<%s ORDER BY id").format(sql.Identifier(table),sql.Identifier(column))
            count=0
            with conn.cursor(name="verify_"+table) as cur:
                cur.execute(query,(cutoff_for(policy,table),))
                while True:
                    batch=cur.fetchmany(1000)
                    if not batch: break
                    keys=[]
                    for row_id,payload in batch:
                        packed=MarketArchive.packed(table,payload)
                        key=packed[:4]; digest=packed[5]
                        for copy in (local,second):
                            stored=copy.execute("SELECT digest,payload FROM market_rows WHERE table_name=? AND company_id=? AND trade_date=? AND source=?",key).fetchone()
                            if stored is None or stored!=(digest,payload):
                                raise RuntimeError("Source changed or archive/backup is incomplete; no cloud rows deleted")
                        keys.append((table,row_id,digest))
                    with conn.cursor().copy("COPY archived_delete_keys FROM STDIN") as copy:
                        for key in keys: copy.write_row(key)
                    count+=len(keys)
            result[table]={"verified_candidates":count,"cutoff":cutoff_for(policy,table)}
        # Activation and both deletes share a transaction; partial pruning rolls back.
        fingerprint=archive.metadata("verified_export")["sha256"]
        conn.execute("UPDATE public.market_history_storage SET enabled=true,price_days=%s,feature_days=%s,project_ref=%s,archived_at=now(),archive_fingerprint=%s WHERE id=1",
                     (policy["price_days"],policy["feature_days"],archive.metadata("project_ref"),fingerprint))
        for table,column in TABLE_DATES.items():
            query=sql.SQL("DELETE FROM public.{} t USING archived_delete_keys k WHERE k.table_name=%s AND t.id=k.id AND md5(to_jsonb(t)::text)=k.digest AND t.{}<%s").format(sql.Identifier(table),sql.Identifier(column))
            deleted=conn.execute(query,(table,cutoff_for(policy,table))).rowcount
            if deleted!=result[table]["verified_candidates"]:
                raise RuntimeError("Verified deletion count mismatch; transaction rolled back")
            result[table]["deleted_rows"]=deleted
    return result


def compact(conn):
    from psycopg import sql
    # Separate from deletion: FULL needs an exclusive lock and free workspace.
    conn.autocommit=True
    try:
        conn.execute("SET lock_timeout='15s'")
        conn.execute("SET statement_timeout='20min'")
        for table in TABLE_DATES:
            conn.execute(sql.SQL("VACUUM (FULL, ANALYZE) public.{}").format(sql.Identifier(table)))
    finally:
        conn.autocommit=False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive",default=os.getenv("LOCAL_MARKET_ARCHIVE",str(API_DIR/"local-data/market-history.sqlite3")))
    parser.add_argument("--backup",default=os.getenv("LOCAL_MARKET_ARCHIVE_BACKUP"))
    parser.add_argument("--prune",action="store_true",help="Delete only expired rows verified in archive AND backup")
    parser.add_argument("--maintain",action="store_true",help="Export only rows now expiring; requires an existing verified full export")
    parser.add_argument("--compact",action="store_true",help="Reclaim table/index space after pruning; briefly locks tables")
    parser.add_argument("--configure",action="store_true",help="Save archive/backup paths to this computer's .env after success")
    parser.add_argument("--check-connection",action="store_true",help="Check connection and read access only; no archive files, data deletion or schema changes")
    args=parser.parse_args()
    if args.check_connection:
        if args.prune or args.compact or args.configure or args.maintain:
            parser.error("--check-connection cannot be combined with migration actions")
        progress("database connection check")
        with connection() as conn:
            from psycopg import sql
            conn.execute("SET TRANSACTION READ ONLY")
            conn.execute("SELECT 1")
            for table in TABLE_DATES:
                conn.execute(sql.SQL("SELECT 1 FROM public.{} LIMIT 1").format(sql.Identifier(table)))
        print("Connection and read access to both market-history tables succeeded. No archive or cloud-data changes were made.")
        return
    if args.prune and not args.backup: parser.error("--prune requires --backup (a second file, preferably another disk)")
    if args.compact and not args.prune: parser.error("--compact requires --prune")
    ref=project_ref(os.environ.get("SUPABASE_URL",""))
    archive=MarketArchive(args.archive,create=not args.maintain)
    if args.maintain: archive.require_verified(ref)
    previous=archive.metadata("project_ref")
    if previous and previous!=ref: raise RuntimeError("Archive belongs to another project")
    archive.set_metadata("project_ref",ref)
    policy={"price_days":DEFAULT_DAYS["price_history"],"feature_days":DEFAULT_DAYS["price_features"]}
    progress("database connection")
    with connection() as conn:
        progress("history export")
        report=export(conn,archive,policy,full=not args.maintain)
        progress("archive verification")
        fingerprint=archive.fingerprint()
        if not args.maintain and any(not fingerprint["counts"][t] for t in TABLE_DATES):
            raise RuntimeError("Full export must contain both history tables")
        archive.set_metadata("verified_export",{**fingerprint,"verified_at":datetime.now(timezone.utc).isoformat()})
        if args.backup:
            progress("backup verification")
            archive.backup_verified(args.backup)
        if args.prune:
            # DDL only after the export and independent copy are verified.
            if not args.maintain:
                progress("retention schema installation")
                conn.execute((API_DIR/"sql/local_market_history.sql").read_text())
                conn.commit()
            progress("verified cloud pruning")
            report["pruned"]=prune(conn,archive,args.backup,policy)
            if args.compact:
                progress("database compaction")
                try:
                    compact(conn)
                    report["compaction"]="success"
                except Exception as exc:
                    conn.rollback()
                    report["compaction"]="not completed; archived data is safe. Pause other jobs and rerun --maintain --prune --compact. Reason: "+safe_error(exc)
        progress("remaining database size check")
        report["database_bytes"]=conn.execute("SELECT pg_database_size(current_database())").fetchone()[0]
        conn.commit()
    if args.configure:
        set_key(str(API_DIR/".env"),"LOCAL_MARKET_ARCHIVE",str(archive.path))
        if args.backup: set_key(str(API_DIR/".env"),"LOCAL_MARKET_ARCHIVE_BACKUP",str(Path(args.backup).expanduser().resolve()))
    report["archive"]=str(archive.path); report["verified_archive"]=fingerprint
    report["below_free_database_limit"]=report["database_bytes"]<500_000_000
    report["quota_note"]="Existing egress is not refunded; removing a Fair Use restriction may require the next billing cycle."
    print(json.dumps(report,indent=2))
    if args.prune and not report["below_free_database_limit"]:
        raise RuntimeError("Archive/pruning completed, but the database is still above 500 MB. Review compaction and sizes before treating the Free Plan migration as finished.")


if __name__=="__main__":
    try: main()
    except Exception as exc:
        print(f"Archive migration stopped during {CURRENT_STAGE} ({type(exc).__name__}).",file=sys.stderr)
        print(safe_error(exc),file=sys.stderr)
        print(error_hint(exc),file=sys.stderr)
        sys.exit(1)
