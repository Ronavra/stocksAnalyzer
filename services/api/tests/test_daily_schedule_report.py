import pytest
from scripts import report_daily_schedule as report


class Query:
    def select(self,*args): return self
    def eq(self,*args): return self
    def order(self,*args,**kwargs): return self
    def limit(self,*args): return self
    def execute(self): return type("Result",(),{"data":[]})()


class Db:
    def table(self,name):
        assert name=="pipeline_runs"
        return Query()


@pytest.mark.parametrize("overdue",[True,False])
def test_monitor_fails_on_missed_deadline_and_keeps_timing_summary(monkeypatch,tmp_path,capsys,overdue):
    summary=tmp_path/"summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY",str(summary))
    monkeypatch.setattr(report,"get_supabase",lambda:Db())
    monkeypatch.setattr(report,"schedule_status",lambda run:{"overdue":overdue,"late_start":True,
                        "start_delay_minutes":428,"completed_after_deadline":not overdue})
    if overdue:
        with pytest.raises(SystemExit) as error: report.main(["--check-deadline"])
        assert error.value.code==1
    else:
        report.main(["--check-deadline"])
    assert "::warning::" in capsys.readouterr().out
    assert "Daily schedule:" in summary.read_text()
