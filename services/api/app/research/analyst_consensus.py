"""Observed analyst consensus, not a price target or a return forecast."""
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo

COUNT_KEYS=("strong_buy","buy","hold","sell","strong_sell")
MAX_CAPTURE_AGE_DAYS=7
MAX_PERIOD_AGE_DAYS=45
MIN_ANALYSTS=3


def counts(record):
    values=[]
    for key in COUNT_KEYS:
        value=record.get(key)
        try:
            number=float(value)
            if isinstance(value,bool) or not isfinite(number) or number<0 or not number.is_integer():
                return None
            values.append(int(number))
        except (TypeError,ValueError):
            return None
    return values


def load_snapshots(db, since=None):
    rows=[]; start=0
    while True:
        query=db.table("analyst_consensus_snapshots").select("*")
        if since:
            query=query.gte("observed_at",since)
        page=query.order("observed_at",desc=True).order("company_id").order("source").order("period_date",desc=True).range(start,start+999).execute().data or []
        rows.extend(page)
        if len(page)<1000:
            return rows
        start+=1000


def consensus_score(snapshots,asof,*,live=True,now=None):
    # Live decisions occur when the shortlist is frozen, after data collection.
    # Historical comparisons only use observations captured by that market close.
    cutoff=now or datetime.now(timezone.utc)
    if not live:
        cutoff=datetime.combine(date.fromisoformat(asof),datetime.min.time()).replace(hour=16,tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    neutral={"score":50.,"available":False,"status":"missing","analyst_count":None,
             "source":None,"observed_at":None,"period_date":None}
    available=[]
    for row in snapshots:
        try:
            captured=datetime.fromisoformat(row["observed_at"].replace("Z","+00:00"))
            period=date.fromisoformat(row["period_date"])
            if captured.tzinfo is None or captured>cutoff or period>captured.date():
                continue
            available.append((captured,period,row))
        except (KeyError,ValueError,TypeError):
            continue
    if not available:
        return neutral
    # Latest observation first; never revive an older positive revision.
    captured,period,row=max(available,key=lambda x:(x[0],x[1],x[2].get("source", "")))
    data={**neutral,"source":row.get("source"),"observed_at":row["observed_at"],"period_date":row["period_date"],
          "counts":{k:row.get(k) for k in COUNT_KEYS},
          "price_targets":{k:row.get("target_"+k) for k in ("low","mean","median","high")}}
    if cutoff-captured>timedelta(days=MAX_CAPTURE_AGE_DAYS):
        return {**data,"status":"stale_capture"}
    if (cutoff.date()-period).days>MAX_PERIOD_AGE_DAYS:
        return {**data,"status":"stale_provider_period"}
    values=counts(row)
    if values is None:
        return {**data,"status":"invalid_counts"}
    total=sum(values)
    data["analyst_count"]=total
    if total<MIN_ANALYSTS:
        return {**data,"status":"insufficient_analysts"}
    raw=sum(value*weight for value,weight in zip(values,(100,75,50,25,0)))/total
    # A small group should not have the same influence as broad coverage.
    score=50+(raw-50)*total/(total+5)
    return {**data,"score":round(score,4),"raw_score":round(raw,4),"available":True,"status":"current",
            "buy_share":(values[0]+values[1])/total,
            "score_method":"consensus_shrunk_to_neutral_v1"}
