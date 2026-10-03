"""Free consensus sources; Finnhub is selected only with an explicit API key."""
from datetime import date, datetime, timezone
import os
import httpx

from app.research.analyst_consensus import counts

SOURCE_KEYS={"strong_buy":"strongBuy","buy":"buy","hold":"hold","sell":"sell","strong_sell":"strongSell"}


def month_before(today,months):
    index=today.year*12+today.month-1-months
    return date(index//12,index%12+1,1).isoformat()


def normalize(company_id,records,source,observed_at,targets=None):
    today=datetime.fromisoformat(observed_at.replace("Z","+00:00")).date()
    result=[]
    for record in records:
        period=record.get("period")
        if source=="yahoo_finance":
            if period not in ("0m","-1m","-2m","-3m"):
                continue
            period=month_before(today,abs(int(period[:-1])))
        try:
            parsed=date.fromisoformat(str(period))
        except ValueError:
            continue
        row={"company_id":company_id,"source":source,"observed_at":observed_at,"period_date":parsed.isoformat(),
             **{key:record.get(original) for key,original in SOURCE_KEYS.items()}}
        values=counts(row)
        if values is None or not sum(values) or parsed>today:
            continue
        row.update(dict(zip(SOURCE_KEYS,values)))
        # Current targets must never be attached to older provider months.
        if parsed.isoformat()==month_before(today,0) and targets:
            for key in ("low","mean","median","high"):
                try:
                    value=float(targets.get(key))
                    if 0<value<float("inf"):
                        row["target_"+key]=value
                except (TypeError,ValueError):
                    pass
        result.append(row)
    return result


class ConsensusProvider:
    def __init__(self, source="auto"):
        self.key=os.getenv("FINNHUB_API_KEY")
        self.source=("finnhub" if self.key else "yahoo_finance") if source=="auto" else source
        if self.source=="finnhub" and not self.key:
            raise RuntimeError("FINNHUB_API_KEY is required for Finnhub consensus")

    def fetch(self,ticker):
        if self.source=="finnhub":
            # Header authentication keeps keys out of request URLs and logs.
            response=httpx.get("https://finnhub.io/api/v1/stock/recommendation",
                params={"symbol":ticker},headers={"X-Finnhub-Token":self.key},timeout=20)
            response.raise_for_status()
            data=response.json()
            if not isinstance(data,list):
                raise RuntimeError("Invalid Finnhub consensus response")
            return data,None
        import yfinance as yf
        company=yf.Ticker(ticker.replace(".","-"))
        table=company.get_recommendations()
        if table is None or table.empty:
            return [],None
        try:
            targets=company.get_analyst_price_targets()
        except Exception:
            targets=None  # Targets are supplementary and never affect scoring.
        return table.to_dict("records"),targets
