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
