"""Shared append-only checks and sanitized run finalization."""
from datetime import datetime, timezone
import json


def now():
    return datetime.now(timezone.utc).isoformat()


def start(db, pipeline):
    return db.table('pipeline_runs').insert({'pipeline': pipeline, 'status': 'running', 'started_at': now()}).execute().data[0]['id']


def finish(db, run_id, report):
    status = 'error' if report.get('errors') or report.get('unavailable') else 'success'
    db.table('pipeline_runs').update({'status': status, 'finished_at': now(), 'metadata': report,
                                     'error_message': 'Source collection incomplete; inspect checks' if status == 'error' else None}).eq('id', run_id).execute()
    print(json.dumps(report), flush=True)
    return status


def check(db, family, source, status, company_id=None, **metadata):
    db.table('research_collection_checks').insert({'company_id': company_id, 'family': family, 'source': source,
                                                 'status': status, 'checked_at': now(), 'metadata': metadata}).execute()


def save_events(db, rows):
    if rows:
        db.table('research_evidence_events').upsert(rows, on_conflict='company_id,kind,source,source_record_id,fingerprint', ignore_duplicates=True, returning='minimal').execute()


def save_documents(db, rows):
    if rows:
        db.table('research_documents').upsert(rows, on_conflict='company_id,source_url,content_hash', ignore_duplicates=True, returning='minimal').execute()
