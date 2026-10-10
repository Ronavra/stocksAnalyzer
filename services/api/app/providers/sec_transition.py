"""Recover dollar TTM flows across fiscal transitions from exact reported intervals.

A five-month 10-KT is not a twelve-month annual statement. Interval sums may
bridge the transition only when their start/end dates prove the identity.
EPS is excluded: per-share values do not share a constant denominator.
"""
from collections import deque
from datetime import date,timedelta
import math

TAGS={
 'revenue':('RevenuesNetOfInterestExpense','RevenueFromContractWithCustomerExcludingAssessedTax','RevenueFromContractWithCustomerIncludingAssessedTax','Revenues','SalesRevenueNet'),
 'net_income':('NetIncomeLoss','ProfitLoss'),
 'operating_income':('OperatingIncomeLoss',),
 'operating_cash_flow':('NetCashProvidedByUsedInOperatingActivities',),
 'capex':('PaymentsToAcquirePropertyPlantAndEquipment','PaymentsForAdditionsToPropertyPlantAndEquipment','PaymentsToAcquireProductiveAssets'),
}
FORMS={'10-K','10-K/A','10-Q','10-Q/A','10-KT','10-KT/A','10-QT','10-QT/A'}


def interval_total(rows,start,end,filed):
    selected={};ambiguous=set()
    for r in rows:
        if r.get('form') not in FORMS or not r.get('start') or not r.get('end') or not r.get('filed') or r['filed']>filed:continue
        try:
            left=date.fromisoformat(r['start']);right=date.fromisoformat(r['end'])+timedelta(days=1);value=float(r['val'])
        except (ValueError,TypeError,KeyError):continue
        if not math.isfinite(value) or not 0<(right-left).days<=380 or left<start-timedelta(days=800) or right>end:continue
        key=(left,right);previous=selected.get(key)
        if previous is None or r['filed']>previous['filed']:
            selected[key]=r;ambiguous.discard(key)
        elif r['filed']==previous['filed'] and not math.isclose(value,float(previous['val']),rel_tol=1e-10,abs_tol=.01):
            ambiguous.add(key)
    graph={}
    for (left,right),r in selected.items():
        if (left,right) in ambiguous:continue
        graph.setdefault(left,[]).append((right,1,r))
        graph.setdefault(right,[]).append((left,-1,r))
    queue=deque([(start,0.,[])]);potentials={start:(0.,[])}
    while queue:
        node,total,path=queue.popleft()
        if len(path)>=6:continue
        for target,sign,r in sorted(graph.get(node,[]),key=lambda edge:edge[2]['filed'],reverse=True):
            candidate=total+sign*float(r['val'])
            if target in potentials:
                # Incompatible overlapping reports cannot be resolved by
                # selecting whichever algebraic path happens to be first.
                if not math.isclose(candidate,potentials[target][0],rel_tol=1e-10,abs_tol=.01):return None,None
                continue
            next_path=path+[(sign,r)];potentials[target]=(candidate,next_path)
            queue.append((target,candidate,next_path))
    return potentials.get(end,(None,None))


def transition_ttm(data,report,latest_quarter):
    if not report or not latest_quarter or latest_quarter['period_end']!=report['period_end']:return None
    facts=(data.get('facts') or {}).get('us-gaap') or {}
    end=date.fromisoformat(report['period_end'])+timedelta(days=1)
    try:start=date(end.year-1,end.month,end.day)
    except ValueError:start=date(end.year-1,2,28)
    filed=report.get('filed_date')
    if not filed:return None
    # Restrict this fallback to a documented transition within the history.
    transitions=[r for tag in TAGS['revenue'] for r in ((facts.get(tag) or {}).get('units') or {}).get('USD',[])
                 if r.get('form') in ('10-KT','10-KT/A','10-QT','10-QT/A') and r.get('filed','')<=filed and r.get('end','')>=str(start-timedelta(days=380))]
    if not transitions:return None
    flow_keys={*TAGS,'eps_diluted','free_cash_flow'}
    result={k:v for k,v in latest_quarter.items() if k not in flow_keys}
    provenance={};filed_dates=[latest_quarter.get('filed_date') or '']
    for field,tags in TAGS.items():
        for tag in tags:
            rows=((facts.get(tag) or {}).get('units') or {}).get('USD',[])
            value,path=interval_total(rows,start,end,filed)
            if value is None:continue
            result[field]=value
            provenance[field]={'tag':tag,'start':str(start),'end':report['period_end'],
                               'components':[{'sign':sign,'start':r['start'],'end':r['end'],'value':r['val'],'filed_date':r['filed'],'accession_number':r.get('accn')} for sign,r in path]}
            filed_dates.extend(r['filed'] for _,r in path);break
    if result.get('revenue') is None or result.get('net_income') is None or result['revenue']<0:return None
    result['eps_diluted']=None
    ocf=result.get('operating_cash_flow');capex=result.get('capex')
    result['free_cash_flow']=ocf-abs(capex) if ocf is not None and capex is not None else None
    result['filed_date']=max(filed_dates)
    result['supplemental']={**(result.get('supplemental') or {}),'ttm_interval_basis':provenance,
                            'eps_ttm_basis':'unavailable; interval arithmetic does not establish diluted EPS'}
    return result
