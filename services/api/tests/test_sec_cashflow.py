from app.providers.sec import quarter_facts_by_period
from scripts.ingest_sec_fundamentals import build_ttm_rows


def fact(start, end, fp, value, filed, tag_form="10-Q"):
    return {"start":start,"end":end,"fp":fp,"val":value,"filed":filed,"form":tag_form}


def test_cumulative_sec_cash_flow_becomes_discrete_quarters_and_ttm():
    q1="2025-03-31"; q2="2025-06-30"; q3="2025-09-30"
    first="2025-01-01"
    dates=((q1,"Q1","2025-05-01"),(q2,"Q2","2025-08-01"),(q3,"Q3","2025-11-01"))
    facts={
        "Revenues":{"units":{"USD":[fact("2025-01-01",end,fp,200,i) for end,fp,i in dates]}},
        "NetIncomeLoss":{"units":{"USD":[fact("2025-01-01",end,fp,30,i) for end,fp,i in dates]}},
        "NetCashProvidedByUsedInOperatingActivities":{"units":{"USD":[fact(first,end,fp,val,filed) for (end,fp,filed),val in zip(dates,(100,250,390))]}},
        "PaymentsToAcquirePropertyPlantAndEquipment":{"units":{"USD":[fact(first,end,fp,val,filed) for (end,fp,filed),val in zip(dates,(20,55,90))]}},
    }
    # Core income data is already discrete in a real 10-Q. Use valid quarter
    # starts for Q2/Q3 rather than the cumulative cash-flow start.
    for tag in ("Revenues","NetIncomeLoss"):
        for rec,start in zip(facts[tag]["units"]["USD"],(first,"2025-04-01","2025-07-01")):
            rec["start"]=start

    quarters=quarter_facts_by_period({"facts":{"us-gaap":facts}})
    by_end={x["period_end"]:x for x in quarters}
    assert [(by_end[end]["operating_cash_flow"],by_end[end]["capex"],by_end[end]["free_cash_flow"])
            for end in (q1,q2,q3)]==[(100,20,80),(150,35,115),(140,35,105)]
    assert by_end[q2]["filed_date"]=="2025-08-01"

    annual={"period_end":"2025-12-31","filed_date":"2026-02-01",
            "revenue":800,"net_income":120,"operating_cash_flow":600,"capex":140,"free_cash_flow":460}
    ttm=build_ttm_rows([annual],quarters)
    assert ttm[-1]["period_end"]=="2025-12-31"
    assert ttm[-1]["free_cash_flow"]==460


def test_ytd_derivation_never_uses_a_later_amended_filing():
    core=[fact("2025-01-01","2025-03-31","Q1",100,"2025-05-01"),
          fact("2025-04-01","2025-06-30","Q2",100,"2025-08-01")]
    flows=[fact("2025-01-01","2025-03-31","Q1",100,"2025-05-01"),
           fact("2025-01-01","2025-03-31","Q1",120,"2025-10-01","10-Q/A"),
           fact("2025-01-01","2025-06-30","Q2",250,"2025-08-01")]
    data={"facts":{"us-gaap":{
        "Revenues":{"units":{"USD":core}},
        "NetIncomeLoss":{"units":{"USD":core}},
        "NetCashProvidedByUsedInOperatingActivities":{"units":{"USD":flows}},
        "PaymentsToAcquirePropertyPlantAndEquipment":{"units":{"USD":[
            fact("2025-01-01","2025-03-31","Q1",20,"2025-05-01"),
            fact("2025-01-01","2025-06-30","Q2",55,"2025-08-01")]}}
        }}}
    q2=next(x for x in quarter_facts_by_period(data) if x["period_end"]=="2025-06-30")
    assert q2["operating_cash_flow"]==150
    assert q2["free_cash_flow"]==115
