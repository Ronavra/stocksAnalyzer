from unittest.mock import MagicMock
import pytest
from fastapi import HTTPException
from postgrest.exceptions import APIError
from app.routers import research


def test_timeout_serves_explicitly_flagged_cached_snapshot(monkeypatch):
    db=MagicMock()
    db.rpc.return_value.execute.side_effect=APIError({
        'code':'57014','message':'canceling statement due to statement timeout',
        'details':None,'hint':None
    })
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data=[
        {'metadata':{'families':[{'key':'market','label':'Market','total':503,'covered_companies':502}]},
         'finished_at':'2026-10-25T12:00:00Z','status':'success'}]
    monkeypatch.setattr(research,'get_supabase',lambda:db)
    data=research.data_audit()
    assert data['data_status']=='cached_after_timeout'
    assert data['source_families'][0]['covered_companies']==502
    assert data['company_gaps']==[]
    assert data['all_major_data_complete'] is False


def test_non_timeout_database_error_not_masked(monkeypatch):
    db=MagicMock()
    db.rpc.return_value.execute.side_effect=APIError({'code':'42P01','message':'missing table'})
    monkeypatch.setattr(research,'get_supabase',lambda:db)
    with pytest.raises(APIError):
        research.data_audit()


def test_missing_cached_audit_returns_explicit_unavailable():
    db=MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data=[]
    with pytest.raises(HTTPException) as e:
        research._cached_data_audit(db)
    assert e.value.status_code==503
