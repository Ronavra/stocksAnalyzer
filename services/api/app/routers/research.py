from fastapi import APIRouter, HTTPException
from ..db.client import get_supabase

router=APIRouter(prefix="/api/v1/research",tags=["research"])

@router.get("/candidates")
def candidates():
    db=get_supabase()
    rows=db.table("research_snapshots").select(
        "as_of_date,research_priority_score,research_priority_coverage,research_priority_reason,"
        "fundamentals_score,valuation_score,earnings_score,pe,price_to_fcf,opportunity_score,setup_probability_up,setup_median_return_5d,setup_sample_size,upside_to_60d_high,setup_drawdown_60d,opportunity_reason,"
        "companies!inner(ticker,name,sector,industry,scoring_profile)"
    ).not_.is_("opportunity_score","null").order("opportunity_score",desc=True).limit(503).execute().data or []
    result=[]
    tickers=[row["companies"]["ticker"] for row in rows]
    company_rows=db.table("companies").select("id,ticker").in_("ticker",tickers).execute().data or []
    ids={x["ticker"]:x["id"] for x in company_rows}
    price_rows=[]
    company_ids=list(ids.values())
    for i in range(0,len(company_ids),100):
        price_rows.extend(db.table("price_history").select("company_id,price_date,close,source").in_("company_id",company_ids[i:i+100]).order("price_date",desc=True).limit(1000).execute().data or [])
    latest_prices={}
    for pr in price_rows:
        cid=pr["company_id"]
        cur=latest_prices.get(cid)
        priority=1 if pr.get("source")=="twelvedata" else 0
        if cur is None or pr["price_date"]>cur["price_date"] or (pr["price_date"]==cur["price_date"] and priority>cur["_priority"]):
            latest_prices[cid]={**pr,"_priority":priority}
    for row in rows:
        company=row["companies"]
        price=latest_prices.get(ids.get(company["ticker"]))
        result.append({
          "ticker":company["ticker"],"company":company["name"],"sector":company.get("sector"),
          "signal":"setup","score":row.get("research_priority_score"),"coverage":row.get("research_priority_coverage"),
          "catalyst":row.get("research_priority_reason"),"fundamentals":row.get("fundamentals_score"),
          "valuation":row.get("valuation_score"),"earnings":row.get("earnings_score"),
          "pe":row.get("pe"),"price_to_fcf":row.get("price_to_fcf"),"as_of_date":row.get("as_of_date"),
          "opportunity_score":row.get("opportunity_score"),"setup_probability_up":row.get("setup_probability_up"),
          "setup_median_return_5d":row.get("setup_median_return_5d"),"setup_sample_size":row.get("setup_sample_size"),
          "upside_to_60d_high":row.get("upside_to_60d_high"),"setup_drawdown_60d":row.get("setup_drawdown_60d"),
          "opportunity_reason":row.get("opportunity_reason"),
          "current_price":price.get("close") if price else None,
          "price_date":price.get("price_date") if price else None,
          "price_source":price.get("source") if price else None
        })
    return result

@router.get("/companies/{ticker}")
def company(ticker:str):
    db=get_supabase()
    companies=db.table("companies").select("*").eq("ticker",ticker.upper()).limit(1).execute().data or []
    if not companies: raise HTTPException(404,"Company not found")
    c=companies[0]
    snapshots=db.table("research_snapshots").select("*").eq("company_id",c["id"]).order("as_of_date",desc=True).limit(12).execute().data or []
    return {"company":c,"snapshots":snapshots}

@router.get("/framework")
def framework():
    return {"dimensions":["fundamentals","valuation","earnings/revisions","momentum","news/sentiment","catalysts"],
            "purpose":"Prioritize companies for research; not personalized buy/sell instructions."}
