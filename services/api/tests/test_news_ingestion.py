import asyncio
import pytest
from app.providers.massive import MassiveProvider
from app.research.news import article_rows, news_summary


def test_article_maps_only_related_companies_and_preserves_unknown_sentiment():
    article={"id":"a","title":"Company updates","published_utc":"2026-10-05T18:00:00Z","article_url":"https://publisher.example/a",
             "tickers":["BRK.B","ABC","OUTSIDE"],"insights":[{"ticker":"BRK.B","sentiment":"negative"}]}
    rows=article_rows(article,{"BRK-B":1,"ABC":2},"2026-10-06T18:00:00Z")
    assert len(rows)==2
    by_id={r['company_id']:r for r in rows}
    assert by_id[1]['sentiment']==-1 and by_id[2]['sentiment'] is None
    assert all(r['created_at']=="2026-10-06T18:00:00Z" for r in rows)
    assert news_summary(rows,"2026-10-05T20:00:00Z")['articles']==0
    assert news_summary(rows,"2026-10-06T20:00:00Z")['sentiment_observations']==1


def test_news_pagination_keeps_authorization_on_the_provider_host(monkeypatch):
    provider=MassiveProvider("test-only")
    calls=[]
    async def get(path,params):
        calls.append((path,params))
        return {"results":[{"id":len(calls)}],"next_url":"https://api.massive.com:443/v2/reference/news?cursor=next&apiKey=must-not-be-logged"} if len(calls)==1 else {"results":[{"id":2}]}
    monkeypatch.setattr(provider,"_get",get)
    assert len(asyncio.run(provider.news("2026-10-05","2026-10-06")))==2
    assert calls[1][1]=={"cursor":"next"}


def test_pagination_rejects_external_hosts_and_never_returns_truncated_results(monkeypatch):
    provider=MassiveProvider("test-only")
    async def get(*args):
        return {"results":[{}],"next_url":"https://attacker.example/v2/reference/news?cursor=next"}
    monkeypatch.setattr(provider,"_get",get)
    with pytest.raises(RuntimeError,match="Invalid"):
        asyncio.run(provider.news("2026-10-05","2026-10-06"))


def test_guidance_uses_documented_date_order_while_filtering_updates(monkeypatch):
    provider=MassiveProvider('test-only')
    async def get(path,params):
        assert path=='/benzinga/v1/guidance'
        assert params['sort']=='date.asc' and params['last_updated.gte']=='2026-10-01T00:00:00Z'
        return {'results':[]}
    monkeypatch.setattr(provider,'_get',get)
    assert asyncio.run(provider.guidance(updated_since='2026-10-01T00:00:00Z'))==[]


def test_vendor_adjusted_guidance_preserves_basis_and_stable_revision_identity():
    from scripts.ingest_massive_guidance import payload_for
    value={'date':'2026-10-01','benzinga_id':'a','eps_method':'adj','min_eps_guidance':2,'max_eps_guidance':3}
    first=payload_for(1,value,'2026-10-02T18:00:00Z')
    repeated=payload_for(1,value,'2026-10-05T18:00:00Z')
    revised=payload_for(1,{**value,'max_eps_guidance':4},'2026-10-05T18:00:00Z')
    assert first['eps_method']=='adjusted'
    assert first['source_record_id']==repeated['source_record_id']!=revised['source_record_id']


def test_provider_error_reports_cause_without_key_or_request_url(monkeypatch):
    import httpx
    key='dummy-sensitive-api-key'
    original=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(400,json={'error':f'Invalid sort; apiKey={key} URL https://api.massive.com/path?apiKey={key}'}))
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:original(transport=transport,**kwargs))
    with pytest.raises(RuntimeError) as error:
        asyncio.run(MassiveProvider(key)._get('/benzinga/v1/guidance'))
    message=str(error.value)
    assert 'Invalid sort' in message and key not in message and 'https://' not in message
