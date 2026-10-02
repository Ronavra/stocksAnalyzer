from app.research.signal_history import complete_oldest_signal_cohort


def test_row_limit_does_not_truncate_last_visible_shortlist():
    older=[{"id":i,"signal_date":"2026-09-25"} for i in range(1,16)]
    latest=[{"id":20,"signal_date":"2026-10-02"}]

    class Query:
        data=older
        def select(self,*args): return self
        def eq(self,key,value):
            assert (key,value)==("signal_date","2026-09-25")
            return self
        def order(self,*args): return self
        def execute(self): return self

    class Db:
        def table(self,name):
            assert name=="research_predictions"
            return Query()

    assert complete_oldest_signal_cohort(Db(),latest+older[:10])==latest+older


def test_empty_history_needs_no_followup_query():
    assert complete_oldest_signal_cohort(None,[])==[]
