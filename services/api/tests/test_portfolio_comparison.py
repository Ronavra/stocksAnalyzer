from datetime import date, timedelta
import pytest

from app.market_calendar import is_trading_day
from app.research.portfolio_comparison import simulate, compare_portfolios, entry_index
from scripts.refresh_portfolio_returns import normalized_series


def calendar(n=16):
    day=date(2026,1,5)
    rows=[]
    while len(rows)<n:
        if is_trading_day(day):
            rows.append(day.isoformat())
        day+=timedelta(days=1)
    return rows


def cohort(signal="2026-01-02",picks=1,version="v1",published="2026-01-04T12:00:00Z"):
    return {"signal_date":signal,"model_version":version,"published_at":published,
            "expected_picks":picks,"status":"published","horizons":[5,10,20]}


def prediction(group,cid=1):
    return [{"company_id":cid,"signal_date":group["signal_date"],"model_version":group["model_version"],
             "horizon_days":h} for h in (5,10,20)]


def bars(days,stock=None,spy=None):
    return [{"company_id":cid,"price_date":d,"close":values[i] if values else 100.,"source":"twelvedata"}
            for cid,values in ((1,stock),(99,spy)) for i,d in enumerate(days)]


def test_buy_sell_costs_and_same_day_reinvestment_preserve_one_capital_pool():
    days=calendar(11)
    a=cohort(); b=cohort("2026-01-09",published="2026-01-11T12:00:00Z")
    rows=bars(days,[100.]*5+[110.]*6)
    result=simulate([a,b],prediction(a)+prediction(b),rows,days,99,5,.002)
    first_proceeds=10000/1.001*1.1*.999
    final=first_proceeds/1.001*.999
    assert result["status"]=="ok"
    assert result["summary"]["portfolio_value"]==pytest.approx(final)
    assert result["summary"]["completed_cohorts"]==2
    assert result["summary"]["unfunded_cohorts"]==0
    assert result["summary"]["benchmark_value"]==pytest.approx(10000/1.001)
    assert result["summary"]["cash_fraction"]==1
    assert result["summary"]["annualized_return"] is None
    assert result["validated_forecast"] is False


def test_overlapping_ten_day_positions_share_capital_without_double_counting():
    days=calendar(10)
    a=cohort(); b=cohort("2026-01-09",published="2026-01-11T12:00:00Z")
    result=simulate([a,b],prediction(a)+prediction(b),bars(days),days,99,10,0)
    assert result["sleeves"]==2
    assert result["summary"]["portfolio_value"]==pytest.approx(10000)
    assert result["summary"]["traded_notional"]==pytest.approx(10000)
    assert result["curve"][4]["cash"]==5000
    assert result["curve"][5]["cash"]==0
    assert result["summary"]["open_cohorts"]==2


def test_extra_publication_with_committed_capital_is_unfunded():
    days=calendar(6)
    a=cohort(); b=cohort("2026-01-06",published="2026-01-07T12:00:00Z")
    result=simulate([a,b],prediction(a)+prediction(b),bars(days),days,99,5,0)
    assert result["summary"]["funded_cohorts"]==1
    assert result["summary"]["unfunded_cohorts"]==1
    assert result["summary"]["portfolio_value"]==10000


def test_no_pick_group_retains_cash_and_loses_to_a_rising_benchmark():
    days=calendar(6)
    group=cohort(picks=0)
    result=simulate([group],[],bars(days,spy=[100,102,104,106,108,110]),days,99,5,0)
    assert result["summary"]["cumulative_return"]==0
    assert result["summary"]["excess_return"]==pytest.approx(-.1)
    assert result["summary"]["trading_costs"]==0
    assert result["summary"]["completed_cohorts"]==1


def test_publication_after_close_defers_entry_and_respects_early_close():
    days=calendar()
    group=cohort(published="2026-01-05T21:01:00Z")
    assert entry_index(group,days)==1
    early=cohort("2026-11-25",published="2026-11-27T18:01:00Z")
    assert entry_index(early,["2026-11-25","2026-11-27","2026-11-30"])==2


def test_missing_mark_blocks_at_last_complete_day_instead_of_forward_filling():
    days=calendar(6); group=cohort()
    rows=[r for r in bars(days) if not (r["company_id"]==1 and r["price_date"]==days[2])]
    result=simulate([group],prediction(group),rows,days,99,5,0)
    assert result["status"]=="blocked"
    assert result["summary"]["as_of_date"]==days[1]
    assert result["issues"][0]["company_ids"]==[1]


def test_incomplete_cohort_is_not_replaced_or_treated_as_cash():
    days=calendar(6); group=cohort(picks=2)
    result=simulate([group],prediction(group),bars(days),days,99,5)
    assert result["status"]=="blocked"
    assert result["curve"]==[]
    assert result["issues"][0]["reason"]=="incomplete_frozen_cohort"


def test_dividend_adjusted_basis_remains_separate_and_policies_do_not_mix():
    days=calendar(6); group=cohort()
    raw=bars(days); adjusted=bars(days,[100,100,100,101,101,101])
    report=compare_portfolios([group],prediction(group),raw,adjusted,99,"v2")
    price=report["by_policy"]["v1"]["5"]["price_return"]["base"]
    total=report["by_policy"]["v1"]["5"]["total_return"]["base"]
    assert total["summary"]["portfolio_value"]>price["summary"]["portfolio_value"]
    assert report["by_policy"]["v2"]["5"]["total_return"]["base"]["status"]=="pending"
    absent=compare_portfolios([group],prediction(group),raw,[],99,"v1")
    assert absent["by_policy"]["v1"]["5"]["total_return"]["base"]["status"]=="blocked"
    assert absent["by_policy"]["v1"]["5"]["price_return"]["base"]["status"]=="ok"


def test_spy_calendar_gap_cannot_shorten_holding_period():
    days=calendar(6); group=cohort()
    rows=[r for r in bars(days) if not (r["company_id"]==99 and r["price_date"]==days[2])]
    report=compare_portfolios([group],prediction(group),rows,[],99,"v1")
    result=report["by_policy"]["v1"]["5"]["price_return"]["base"]
    assert result["status"]=="blocked"
    assert result["issues"][0]["date"]==days[2]


def test_drawdown_uses_daily_equity_peaks_and_stress_costs_reduce_returns():
    days=calendar(6); group=cohort()
    rows=bars(days,[100,120,90,100,110,110])
    base=simulate([group],prediction(group),rows,days,99,5,.002)
    stress=simulate([group],prediction(group),rows,days,99,5,.005)
    assert base["summary"]["max_drawdown"]==pytest.approx(-.25)
    assert stress["summary"]["cumulative_return"]<base["summary"]["cumulative_return"]


def test_missing_leading_benchmark_history_cannot_move_the_original_entry():
    days=calendar(6); group=cohort()
    rows=[r for r in bars(days) if not (r["company_id"]==99 and r["price_date"]==days[0])]
    report=compare_portfolios([group],prediction(group),rows,[],99,"v1")
    result=report["by_policy"]["v1"]["5"]["price_return"]["base"]
    assert result["status"]=="blocked"
    assert result["curve"]==[]
    assert result["issues"][0]["date"]==days[0]


def test_atomic_adjusted_snapshot_rejects_gaps_invalid_and_conflicting_prices():
    rows=[{"price_date":"2026-01-05","close":"100"}]
    assert normalized_series(rows,{"2026-01-05"},"2026-01-05")==[{"price_date":"2026-01-05","close":100.}]
    with pytest.raises(RuntimeError,match="missing"):
        normalized_series(rows,{"2026-01-06"},"2026-01-06")
    with pytest.raises(RuntimeError,match="invalid"):
        normalized_series([{"price_date":"2026-01-05","close":"NaN"}],set(),"2026-01-05")
    with pytest.raises(RuntimeError,match="conflicting"):
        normalized_series(rows+[{"price_date":"2026-01-05","close":99}],set(),"2026-01-05")
