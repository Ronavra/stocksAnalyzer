from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from app.routers import research


def test_data_audit_uses_one_rpc_and_preserves_unknown_company_gaps(monkeypatch):
    now=datetime.now(timezone.utc)
    snapshot={'audit':{'universe':1,'prices':1,'features':1,'fundamentals':1},
              'counts':{'analyst_consensus':1},'financial_report':{},'source_checks':[],
              'inventory':[{'company_id':1,'ticker':'TEST'}],
              'calendars':[{'company_id':1,'source':'yahoo_finance','status':'observed',
                            'observed_at':now.isoformat(),'dates':[(now+timedelta(days=10)).date().isoformat()]}]}
    calls=[]
    class Db:
        def rpc(self,name):
            calls.append(name)
            return SimpleNamespace(execute=lambda:SimpleNamespace(data=snapshot))
        def table(self,*args):
            raise AssertionError('The audit must not download paged source tables')
    monkeypatch.setattr(research,'get_supabase',lambda:Db())
    result=research.data_audit()
    assert calls==['research_dashboard_data_audit']
    assert result['universe']==1 and len(result['source_families'])==15
    families={x['key']:x for x in result['source_families']}
    assert families['upcoming']['status_counts']=={'current':1}
    assert families['financials']['status_counts']=={'missing':1}
    assert result['company_gaps'][0]['ticker']=='TEST'
    assert not result['all_major_data_complete']
    assert next(x for x in result['layers'] if x['key']=='analyst_consensus')['companies']==1
