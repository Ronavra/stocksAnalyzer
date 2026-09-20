from fastapi import APIRouter, HTTPException
from ..db.client import get_supabase

router=APIRouter(prefix="/api/v1/research",tags=["research"])

@router.get("/candidates")
def candidates():
    db=get_supabase()
    rows=db.rpc("research_dashboard_candidates").execute().data or []
    return [{
      "ticker":r["ticker"],"company":r["company"],"sector":r.get("sector"),"signal":"setup",
      "score":r.get("research_priority_score"),"coverage":r.get("research_priority_coverage"),
      "catalyst":r.get("research_priority_reason"),"fundamentals":r.get("fundamentals_score"),
      "valuation":r.get("valuation_score"),"earnings":r.get("earnings_score"),"pe":r.get("pe"),
      "price_to_fcf":r.get("price_to_fcf"),"as_of_date":r.get("as_of_date"),
      "opportunity_score":r.get("opportunity_score"),"setup_probability_up":r.get("setup_probability_up"),
      "setup_median_return_5d":r.get("setup_median_return_5d"),"setup_sample_size":r.get("setup_sample_size"),
      "upside_to_60d_high":r.get("upside_to_60d_high"),"setup_drawdown_60d":r.get("setup_drawdown_60d"),
      "opportunity_reason":r.get("opportunity_reason"),"current_price":r.get("current_price"),
      "price_date":r.get("price_date"),"price_source":r.get("price_source")
    } for r in rows]

@router.get("/data-audit")
def data_audit():
    db=get_supabase()
    d=db.rpc("research_data_audit").execute().data or {}
    total=d.get("universe",0)
    def item(key,label,status):
        count=d.get(key,0)
        return {"key":key,"label":label,"companies":count,"total":total,
                "coverage_pct":round(100*count/total,1) if total else 0,"status":status}
    return {"universe":total,"layers":[
      item("prices","Daily prices","strong"),item("features","Price features","strong"),
      item("setups","Current setup metrics","strong"),item("fundamentals","Fundamentals","partial"),
      item("valuation","Valuation","partial"),item("estimates","Analyst estimates","partial"),
      item("earnings","Historical earnings events","partial")],
      "missing_price_tickers":d.get("missing_price_tickers",[]),
      "notes":["Price/setup data is the strongest current layer.",
               "Fundamentals, valuation, estimates and earnings-event coverage are currently pilot-scale."]}

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
