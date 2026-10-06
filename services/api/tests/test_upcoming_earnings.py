from app.research.earnings_catalysts import upcoming_earnings

class Query:
    def __init__(self,rows): self.rows=rows
    def select(self,*args): return self
    def in_(self,col,values): self.rows=[r for r in self.rows if r[col] in values];return self
    def gt(self,col,value): self.rows=[r for r in self.rows if r[col]>value];return self
    def gte(self,col,value): self.rows=[r for r in self.rows if r[col]>=value];return self
    def lte(self,col,value): self.rows=[r for r in self.rows if r[col]<=value];return self
    def is_(self,col,value): self.rows=[r for r in self.rows if r.get(col) is None];return self
    def order(self,col): self.rows.sort(key=lambda r:r[col]);return self
    def limit(self,n): self.rows=self.rows[:n];return self
    def execute(self): return type('Result',(),{'data':self.rows})()

def test_upcoming_reports_respect_trading_windows_and_capture_time():
    events=[{'company_id':1,'reported_date':'2026-09-14','reported_eps':None,'captured_at':'2026-09-03'},
            {'company_id':1,'reported_date':'2026-09-09','reported_eps':1,'captured_at':'2026-09-03'},
            {'company_id':2,'reported_date':'2026-09-08','reported_eps':None,'captured_at':'2026-09-06'},
            {'company_id':3,'reported_date':'2026-09-15','reported_eps':None,'captured_at':'2026-09-03'}]
    class Db:
        def table(self,name): assert name=='earnings_events';return Query(events.copy())
    result=upcoming_earnings(Db(),[{'company_id':i} for i in (1,2,3)],'2026-09-04','2026-09-05')
    assert set(result)=={1,3}
    assert result[1]['within_horizons']==[5,10,20] # Labor Day is excluded.
    assert result[3]['within_horizons']==[10,20]
    assert result[1]['date_status']=='expected'
