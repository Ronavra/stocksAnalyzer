"""Provider-attributed article sentiment; missing sentiment is unknown."""
from datetime import datetime, timedelta, timezone
from .observations import available, close_cutoff

SENTIMENT={"positive":1., "negative":-1., "neutral":0.}


def article_rows(article, companies, observed_at):
    published=article.get("published_utc")
    url=article.get("article_url") or ""
    if not published or not url.startswith(("https://", "http://")) or not article.get("id") or not article.get("title"):
        return []
    # Do not copy full publisher descriptions. Store only metadata and a short
    # provider-supplied sentiment rationale, with explicit attribution.
    insights={str(x.get("ticker") or "").upper().replace(".","-"):x for x in article.get("insights") or []}
    rows=[]
    for ticker in set(str(t).upper().replace(".","-") for t in article.get("tickers") or []):
        if ticker not in companies:
            continue
        insight=insights.get(ticker) or {}
        row={"company_id":companies[ticker], "published_at":published, "created_at":observed_at,
             "headline":article["title"][:500],"source":"massive_news", "source_record_id":str(article["id"]),
             "source_url":url,"sentiment":SENTIMENT.get(insight.get("sentiment")),
             "sentiment_method":"provider_supplied" if insight.get("sentiment") in SENTIMENT else None,
             "why_it_matters":(insight.get("sentiment_reasoning") or "")[:500] or None,
             "summary":None,"publisher":(article.get("publisher") or {}).get("name")}
        if available(row, observed_at, observed_key="created_at"):
            rows.append(row)
    return rows


def news_summary(rows, cutoff=None):
    cutoff=cutoff or datetime.now(timezone.utc)
    if isinstance(cutoff,str):
        cutoff=datetime.fromisoformat(cutoff.replace("Z","+00:00"))
    eligible=[r for r in rows if available(r,cutoff,observed_key="created_at")
              and datetime.fromisoformat(r["published_at"].replace("Z","+00:00"))>=cutoff-timedelta(days=7)]
    values=[float(r["sentiment"]) for r in eligible if r.get("sentiment") is not None]
    return {"articles":len(eligible),"sentiment_observations":len(values),
            "mean_provider_sentiment":sum(values)/len(values) if values else None,
            "sentiment_method":"provider_supplied", "affects_selection":False}
