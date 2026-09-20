from fastapi import APIRouter, HTTPException
from ..db.client import get_supabase

router=APIRouter(prefix="/api/v1/research",tags=["research"])

@router.get("/candidates")
def candidates():
    db=get_supabase()
    rows=[]
    page_size=1000
    start=0
    while True:
        batch=db.table("research_snapshots").select(
            "as_of_date,research_priority_score,research_priority_coverage,research_priority_reason,"
            "fundamentals_score,valuation_score,earnings_score,pe,price_to_fcf,opportunity_score,setup_probability_up,setup_median_return_5d,setup_sample_size,upside_to_60d_high,setup_drawdown_60d,opportunity_reason,"
            "companies!inner(ticker,name,sector,industry,scoring_profile)"
        ).order("as_of_date",desc=True).range(start,start+page_size-1).execute().data or []
        rows.extend(batch)
        if len(batch)<page_size: break
        start+=page_size
    latest={}
    for row in rows:
        ticker=row["companies"]["ticker"]
        if ticker not in latest: latest[ticker]=row
    result=[]
    for ticker,row in latest.items():
        company=row["companies"]
        result.append({
          "ticker":ticker,"company":company["name"],"sector":company.get("sector"),
          "signal":"research" if row.get("research_priority_score") is not None else "insufficient-data",
          "score":row.get("research_priority_score"),"coverage":row.get("research_priority_coverage"),
          "catalyst":row.get("research_priority_reason"),"fundamentals":row.get("fundamentals_score"),
          "valuation":row.get("valuation_score"),"earnings":row.get("earnings_score"),
          "pe":row.get("pe"),"price_to_fcf":row.get("price_to_fcf"),"as_of_date":row.get("as_of_date"),"opportunity_score":row.get("opportunity_score"),"setup_probability_up":row.get("setup_probability_up"),"setup_median_return_5d":row.get("setup_median_return_5d"),"setup_sample_size":row.get("setup_sample_size"),"upside_to_60d_high":row.get("upside_to_60d_high"),"setup_drawdown_60d":row.get("setup_drawdown_60d"),"opportunity_reason":row.get("opportunity_reason")
        })
    return sorted(result,key=lambda x:(x.get("opportunity_score") is not None,x.get("opportunity_score") or -1),reverse=True)

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
