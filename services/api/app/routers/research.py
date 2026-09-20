from fastapi import APIRouter, HTTPException
from ..db.client import get_supabase

router=APIRouter(prefix="/api/v1/research",tags=["research"])

@router.get("/candidates")
def candidates():
    db=get_supabase()
    rows=db.table("research_snapshots").select(
        "company_id,as_of_date,research_priority_score,research_priority_coverage,research_priority_reason,"
        "fundamentals_score,valuation_score,earnings_score,pe,price_to_fcf,opportunity_score,setup_probability_up,setup_median_return_5d,setup_sample_size,upside_to_60d_high,setup_drawdown_60d,opportunity_reason,"
        "companies!inner(ticker,name,sector,industry,scoring_profile)"
    ).not_.is_("opportunity_score","null").order("opportunity_score",desc=True).limit(503).execute().data or []
    result=[]
    for row in rows:
        company=row["companies"]
        price_rows=(db.table("price_history").select("price_date,close,source")
                    .eq("company_id",row["company_id"]).order("price_date",desc=True).limit(10).execute().data or [])
        price=None
        if price_rows:
            newest=price_rows[0]["price_date"]
            same_day=[p for p in price_rows if p["price_date"]==newest]
            price=next((p for p in same_day if p.get("source")=="twelvedata"),same_day[0])
        result.append({
          "ticker":company["ticker"],"company":company["name"],"sector":company.get("sector"),
          "signal":"setup","score":row.get("research_priority_score"),"coverage":row.get("research_priority_coverage"),
          "catalyst":row.get("research_priority_reason"),"fundamentals":row.get("fundamentals_score"),
          "valuation":row.get("valuation_score"),"earnings":row.get("earnings_score"),
          "pe":row.get("pe"),"price_to_fcf":row.get("price_to_fcf"),"as_of_date":row.get("as_of_date"),
          "opportunity_score":row.get("opportunity_score"),"setup_probability_up":row.get("setup_probability_up"),
          "setup_median_return_5d":row.get("setup_median_return_5d"),"setup_sample_size":row.get("setup_sample_size"),
          "upside_to_60d_high":row.get("upside_to_60d_high"),"setup_drawdown_60d":row.get("setup_drawdown_60d"),
          "opportunity_reason":row.get("opportunity_reason"),"current_price":price.get("close") if price else None,
          "price_date":price.get("price_date") if price else None,"price_source":price.get("source") if price else None
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
