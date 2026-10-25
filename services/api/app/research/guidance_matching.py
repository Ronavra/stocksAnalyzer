"""Explicit fiscal end/currency/basis matches against pre-publication consensus."""
from datetime import datetime,timedelta
import re
from .observations import timestamp
from .weekly_rank_metrics import number


def explicit_target(guidance):
    evidence=guidance.get('evidence') or {};text=evidence.get('excerpt') or ''
    match=re.search(r'\b(?:ending|ends on|ending on)\s+(\d{4}-\d{2}-\d{2}|[A-Za-z]+ \d{1,2},? \d{4})\b',text,re.I)
    if not match:return None,None
    raw=match[1]
    try:day=datetime.strptime(raw,'%Y-%m-%d').date()
    except ValueError:
        try:day=datetime.strptime(raw.replace(',',''),'%B %d %Y').date()
        except ValueError:return None,None
    currency='USD' if re.search(r'\bUSD\b|U\.S\. dollars|US\$',text,re.I) else None
    return day.isoformat(),currency


def match(guidance,estimates,observed_at):
    target,currency=explicit_target(guidance)
    publication=timestamp(guidance.get('published_at'))
    if not target or not currency or not publication:return [],'explicit_target_currency_or_publication_missing'
    fiscal_period=guidance.get('fiscal_period')
    period_type='annual' if fiscal_period=='FY' else 'quarter' if fiscal_period in ('Q1','Q2','Q3','Q4') else None
    if not period_type:return [],'fiscal_period_unknown'
    result=[]
    for metric in ('eps','revenue'):
        low,high=number(guidance.get(metric+'_guidance_low')),number(guidance.get(metric+'_guidance_high'))
        if low is None or high is None or low>high:continue
        method=(guidance.get('eps_method') or '').lower()
        basis='gaap' if method=='gaap' else 'adjusted' if method in ('adjusted','non-gaap') else None
        if metric=='eps' and basis is None:continue
        eligible=[]
        for e in estimates:
            capture=timestamp(e.get('captured_at'))
            if (e.get('company_id')!=guidance['company_id'] or e.get('fiscal_period_end')!=target
                or e.get('period_type')!=period_type or not capture or not publication-timedelta(days=7)<=capture<publication
                or e.get(metric+'_currency')!=currency or number(e.get(metric+'_consensus')) is None):continue
            if metric=='eps' and e.get('eps_basis')!=basis:continue
            if metric+'_consensus_outside_interval' in (e.get('normalization') or {}).get('issues',[]):continue
            eligible.append(e)
        if not eligible:continue
        e=max(eligible,key=lambda e:e['captured_at'])
        result.append(dict(guidance_event_id=guidance['id'],estimate_snapshot_id=e['id'],metric=metric,
            fiscal_period_end=target,accounting_basis=basis if metric=='eps' else 'reported_revenue',currency=currency,
            consensus=e[metric+'_consensus'],guidance_midpoint=(low+high)/2,observed_at=observed_at,
            evidence={'protocol':'explicit-fiscal-target-v1','consensus_captured_at':e['captured_at'],
                      'guidance_published_at':guidance['published_at'],'excerpt':(guidance.get('evidence') or {}).get('excerpt')}))
    return result,'matched' if result else 'no_comparable_prepublication_consensus'
