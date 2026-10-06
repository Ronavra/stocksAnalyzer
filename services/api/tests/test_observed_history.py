from app.research.observations import close_cutoff, financial_versions, member_asof
from app.research.financial_ranking import financial_snapshot
from app.research.calibrated_model import observed_fundamental_asof, guidance_asof, news_asof


def version(value,observed):
    return {"company_id":1,"period_end":"2026-06-30","observed_at":observed,"provenance":"live_ingestion",
            "snapshot":{"company_id":1,"period_type":"ttm","period_end":"2026-06-30","filed_date":"2026-08-01",
                        "revenue":100,"net_income":10,"eps_diluted":value}}


def test_backfilled_filing_and_later_restatement_are_not_available_early():
    rows=[version(2,"2026-10-02T19:00:00Z"),version(9,"2026-10-05T21:00:00Z")]
    assert financial_versions(rows,close_cutoff("2026-10-01"))==[]
    assert financial_versions(rows,close_cutoff("2026-10-02"))[0]["eps_diluted"]==2
    assert financial_versions(rows,close_cutoff("2026-10-05"))[0]["eps_diluted"]==2
    assert financial_versions(rows,close_cutoff("2026-10-06"))[0]["eps_diluted"]==9
    raw=[{**r["snapshot"],"observed_at":r["observed_at"]} for r in rows]
    assert observed_fundamental_asof(raw,"2026-10-01")["fund_net_margin"] is None
    assert observed_fundamental_asof(raw,"2026-10-05")["_ttm_eps"]==2


def test_recorded_membership_uses_half_open_intervals_without_current_universe_fallback():
    rows=[{"company_id":1,"effective_from":"2026-09-21","effective_to":"2026-10-05"}]
    assert not member_asof(rows,1,"2026-09-20")
    assert member_asof(rows,1,"2026-10-02")
    assert not member_asof(rows,1,"2026-10-05")
    assert not member_asof(rows,2,"2026-10-02")


def test_guidance_and_news_require_both_publication_and_actual_observation():
    item={"event_date":"2026-08-01","captured_at":"2026-10-06T18:00:00Z","eps_method":"adjusted",
          "values":{"guidance_eps_gap":.2}}
    assert guidance_asof({1:[item]},1,"2026-10-05")["guidance_eps_gap"] is None
    assert guidance_asof({1:[item]},1,"2026-10-06")["guidance_eps_gap"]==.2
    news={1:[{"published_at":"2026-10-05T18:00:00Z","created_at":"2026-10-06T18:00:00Z","sentiment":-1}]}
    assert news_asof(news,1,"2026-10-05")["news_provider_sentiment_7d"] is None
    assert news_asof(news,1,"2026-10-06")["news_provider_sentiment_7d"]==-1


def test_earnings_revisions_and_beat_streak_use_only_observed_values():
    from app.research.calibrated_model import earnings_asof
    def event(key,day,surprise,observed):
        return {'event_id':key,'available_date':day,'reported_date':day,'observed_at':observed,'reported':True,
                'values':{'earnings_eps_surprise':surprise}}
    events={1:[event(1,'2026-04-01',.1,'2026-10-02T18:00:00Z'),
               event(2,'2026-07-01',.2,'2026-10-02T18:00:00Z'),
               event(2,'2026-07-01',-.3,'2026-10-05T21:00:00Z')]}
    assert earnings_asof(events,1,'2026-10-01')['earnings_eps_surprise'] is None
    assert earnings_asof(events,1,'2026-10-05')['earnings_beat_streak']==2
    assert earnings_asof(events,1,'2026-10-06')['earnings_eps_surprise']==-.3
    assert earnings_asof(events,1,'2026-10-06')['earnings_beat_streak']==0


def test_guidance_merges_separate_metric_rows_only_for_same_fiscal_period():
    base={'event_date':'2026-10-01','captured_at':'2026-10-02T18:00:00Z','fiscal_year':2026,'fiscal_period':'FY'}
    rows=[{**base,'eps_method':'adjusted','values':{'guidance_eps_change':.2}},
          {**base,'values':{'guidance_revenue_change':.1}},
          {**base,'event_date':'2026-09-30','fiscal_year':2027,'values':{'guidance_revenue_change':.9}}]
    values=guidance_asof({1:rows},1,'2026-10-05')
    assert values['guidance_eps_change']==.2 and values['guidance_revenue_change']==.1
