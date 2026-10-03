from scripts import compare_financial_ranking as replay


def record(cid, outcome=.02):
    return {"company_id":cid,"date":"2026-09-25","target_excess":None if outcome is None else outcome-.01,
            "actual_return":outcome,"spy_return":.01,"selection_close":100,
            "screen_score":100-cid,"setup":{"score":60,"sample_size":100}}


def prepared(records):
    return {"records":records,"latest_date":"2026-10-02"}


def test_selected_missing_outcome_excludes_paired_week_without_replacing_stock(monkeypatch):
    records=[record(i) for i in range(1,7)]+[record(7,None)]
    def select(rows,*args,**kwargs):
        assert kwargs["live"] is False
        assert len(rows)==7  # Missing outcomes do not filter the selection universe.
        return [{"row":rows[-1]}],{"ranking_eligible":1,"financial_eligible":7}
    monkeypatch.setattr(replay,"rank_candidates",select)
    result=replay.compare(prepared(records),{})
    assert result["all"]["cohorts"]==0
    assert result["excluded"]=={"missing_selected_outcome":1}


def test_cash_week_is_preserved_without_stock_transaction_cost(monkeypatch):
    monkeypatch.setattr(replay,"rank_candidates",lambda *a,**kw:([],{"ranking_eligible":0,"financial_eligible":0}))
    result=replay.compare(prepared([record(i) for i in range(1,7)]),{})
    assert result["all"]["cohorts"]==1
    assert result["all"]["mean_net_return"]==0
    assert result["all"]["weeks_in_cash"]==1
    assert result["all"]["mean_improvement_vs_baseline"]<0


def test_empty_replay_reports_no_evidence():
    result=replay.compare(prepared([]),{})
    assert result["all"]=={"cohorts":0}
    assert result["holdout_start"] is None
    assert result["weights"]=={"financial":.5,"technical":.4,"earnings":.1}
    assert result["validated_forecast"] is False
