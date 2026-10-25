"""Macro inputs known by the decision close, including dated official vintages."""
from datetime import datetime,timedelta,time
from .observations import close_cutoff,timestamp
from .weekly_rank_metrics import number

FEATURES=['macro_fed_funds','macro_yield_2y','macro_yield_10y','macro_curve_10y_2y',
          'macro_cpi_yoy','macro_unemployment','macro_payroll_change','macro_gdp_qoq',
          'macro_dollar_change_20d','macro_oil_change_20d']
MAX_AGES={'DFF':7,'DGS2':7,'DGS10':7,'CPIAUCSL':75,'UNRATE':75,'PAYEMS':75,
          'GDPC1':240,'DTWEXBGS':10,'DCOILWTICO':10}


def macro_asof(rows,day):
    cutoff=close_cutoff(day);chosen={}
    for r in rows:
        observed=timestamp(r.get('observed_at'))
        vintage=r.get('vintage_date') if r.get('source')=='alfred_vintage' else None
        # Date-only original vintages become usable on the FOLLOWING day.
        # A current HTML/CSV backfill is usable only after actual observation.
        known=bool(vintage and vintage<day) or bool(not vintage and observed and observed<=cutoff)
        value=number(r.get('value'));period=r.get('observation_date')
        if not known or value is None or not period or period>day:continue
        key=(r['series_id'],period)
        order=(vintage or (observed.isoformat() if observed else ''),r.get('observed_at') or '')
        if key not in chosen or order>chosen[key][0]:chosen[key]=(order,r)
    grouped={}
    for _,r in chosen.values():grouped.setdefault(r['series_id'],[]).append(r)
    for series in grouped:grouped[series].sort(key=lambda r:r['observation_date'])
    latest={}
    for series,items in grouped.items():
        last=items[-1]
        age=(datetime.fromisoformat(day).date()-datetime.fromisoformat(last['observation_date']).date()).days
        if age<=MAX_AGES.get(series,0):latest[series]=last
    out={k:None for k in FEATURES}
    for series,key in [('DFF','macro_fed_funds'),('DGS2','macro_yield_2y'),('DGS10','macro_yield_10y'),('UNRATE','macro_unemployment')]:
        if series in latest:out[key]=number(latest[series]['value'])
    if out['macro_yield_2y'] is not None and out['macro_yield_10y'] is not None:
        out['macro_curve_10y_2y']=out['macro_yield_10y']-out['macro_yield_2y']
    for series,key,lag,tolerance,change in [('CPIAUCSL','macro_cpi_yoy',365,40,'ratio'),
        ('PAYEMS','macro_payroll_change',31,10,'difference'),('GDPC1','macro_gdp_qoq',91,15,'ratio'),
        ('DTWEXBGS','macro_dollar_change_20d',28,10,'ratio'),('DCOILWTICO','macro_oil_change_20d',28,10,'ratio')]:
        current=latest.get(series)
        if not current:continue
        target=datetime.fromisoformat(current['observation_date']).date()-timedelta(days=lag)
        prior=min(grouped[series],key=lambda r:abs((datetime.fromisoformat(r['observation_date']).date()-target).days))
        distance=abs((datetime.fromisoformat(prior['observation_date']).date()-target).days)
        a,b=number(current['value']),number(prior['value'])
        if distance>tolerance or b in (None,0) or prior['units']!=current['units']:continue
        out[key]=a-b if change=='difference' else a/b-1
    return out
