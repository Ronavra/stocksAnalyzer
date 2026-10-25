"""Preregistered twenty-session, funded-account research. Never auto-publishes buys."""
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from statistics import mean
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from .calibrated_model import _prepare,FEATURE_GROUPS
from .macro_features import FEATURES as MACRO_FEATURES,macro_asof
from .weekly_rank_metrics import number,execution_dates,executed_return,block_lower_bound
from .active_portfolio import advance,INITIAL_CASH
from ..market_calendar import is_trading_day

VERSION='twenty-session-excess-v1'
PROTOCOL='pit_next_close_20d_funded_ten_v1'
HORIZON=20
MIN_ROWS=5000
MIN_TRAIN_DATES=52
MIN_MATURE_DATES=180
MIN_AUDIT_WEEKS=26
FAMILIES=('earnings','fundamentals','valuation','guidance','news','estimates','analyst','macro')
GROUPS={**FEATURE_GROUPS,'macro':MACRO_FEATURES}
BASE=tuple(GROUPS['price']+GROUPS['context'])


def exchange_calendar(first,last):
    current=date.fromisoformat(first);end=date.fromisoformat(last);days=[]
    while current<=end:
        if is_trading_day(current):days.append(current.isoformat())
        current+=timedelta(days=1)
    return days


def prepared_records(prep,macro_rows=()):
    prices=prep['price_history'];spy=prep['spy_id']
    if not spy or not prices.get(spy):raise RuntimeError('Twenty-session research requires exact SPY history')
    calendar=exchange_calendar(min(prices[spy]),prep['latest_date'])
    records=[];macro={}
    for r in prep['rows']:
        cid=r['company_id'];day=r['feature_date']
        if cid==spy:continue
        fd=dict(prep['features'][(cid,day)])
        if day not in macro:macro[day]=macro_asof(macro_rows,day)
        fd.update(macro[day])
        dates=execution_dates(calendar,day,HORIZON)
        actual=executed_return(prices.get(cid,{}),dates)
        benchmark=executed_return(prices[spy],dates)
        base_coverage=sum(number(fd.get(k)) is not None for k in BASE)/len(BASE)
        if base_coverage<.8:continue
        records.append(dict(company_id=cid,date=day,features=fd,actual_return=actual,
            target_excess=actual-benchmark if actual is not None and benchmark is not None else None,
            label_end_date=dates[1] if dates else None,feature_coverage=base_coverage))
    return dict(records=records,prices=prices,calendar=calendar,spy_id=spy,companies=prep['companies'],latest_date=prep['latest_date'])


def training_before(records,boundary):
    return [r for r in records if r['target_excess'] is not None and r['label_end_date']<boundary]


def stage_records(records,family):
    if family=='price_context':return records
    keys=GROUPS[family]
    return [r for r in records if sum(number(r['features'].get(k)) is not None for k in keys)>=max(1,len(keys)//2)]


def matrix(rows,features):
    return np.asarray([[np.nan if number(r['features'].get(k)) is None else float(r['features'][k]) for k in features] for r in rows])


def fit(rows,features):
    if len(rows)<MIN_ROWS or len({r['date'] for r in rows})<MIN_TRAIN_DATES:
        raise RuntimeError('Insufficient matured twenty-session training rows/dates')
    counts=Counter(r['date'] for r in rows)
    weights=np.asarray([len(rows)/(len(counts)*counts[r['date']]) for r in rows])
    x=matrix(rows,features);common=dict(max_depth=3,max_iter=80,learning_rate=.05,min_samples_leaf=80,
        l2_regularization=2.,random_state=42,early_stopping=False)
    models=[]
    for target,quantile in [('target_excess',None),('actual_return',None),('actual_return',.1)]:
        model=HistGradientBoostingRegressor(**common,**({'loss':'quantile','quantile':quantile} if quantile else {}))
        model.fit(x,np.asarray([r[target] for r in rows]),sample_weight=weights);models.append(model)
    return models


def walk_forward(records,dates,family):
    rows=stage_records(records,family);features=list(BASE)+(GROUPS[family] if family!='price_context' else [])
    by_date=defaultdict(list)
    for r in rows:by_date[r['date']].append(r)
    models=None;outputs={};training_sizes=[]
    for index,day in enumerate(dates):
        if models is None or index%13==0:
            train=training_before(rows,day)
            if family!='price_context' and len({r['date'] for r in train})<26:
                raise RuntimeError('Feature family lacks observed training dates')
            models=fit(train,features);training_sizes.append({'before':day,'rows':len(train),'dates':len({r['date'] for r in train})})
        current=by_date.get(day,[])
        if not current:outputs[day]=[];continue
        x=matrix(current,features);excess,absolute,downside=(model.predict(x) for model in models)
        outputs[day]=[dict(company_id=r['company_id'],expected_excess=float(e),expected_return=float(a),downside_p10=float(q))
                      for r,e,a,q in zip(current,excess,absolute,downside)]
    return outputs,training_sizes


def simulate(outputs,prepared,cost=.002):
    days=prepared['calendar'];start=min(outputs);last=max(outputs)
    end_dates=[execution_dates(days,day,HORIZON) for day in outputs]
    end=max(dates[1] for dates in end_dates if dates)
    prices=prepared['prices'];companies=prepared['companies'];state=None;curve=[];issues=[]
    # Supply recent price maps only. Point-in-time features/labels never affect fills.
    for day in [d for d in days if start<=d<=end]:
        candidates=[]
        for p in outputs.get(day,[]):
            if p['expected_return']<=cost or p['expected_excess']<=0:continue
            score=p['expected_excess']-.25*max(0.,-p['downside_p10'])
            if score<=0:continue
            c=companies[p['company_id']]
            candidates.append(dict(company_id=p['company_id'],ticker=c['ticker'],sector=c.get('sector'),score=score))
        # A bounded trailing window still includes every due execution and the
        # benchmark's original entry; old benchmark price is retained separately.
        since=(date.fromisoformat(day)-timedelta(days=130)).isoformat()
        since=min(since,state.get('benchmark_on',since)) if state else since
        pending_ids={o['company_id'] for o in (state or {}).get('orders',[])}
        held_ids={p['company_id'] for p in (state or {}).get('positions',[])}
        ids={p['company_id'] for p in candidates}|pending_ids|held_ids|{prepared['spy_id']}
        bars=[dict(company_id=cid,price_date=d,close=v) for cid in ids for d,v in prices.get(cid,{}).items() if since<=d<=day]
        calendars={cid:{'calendar_status':'current'} for cid in held_ids}
        state=advance(state,candidates,bars,day,datetime.fromisoformat(day+'T23:59:00+00:00'),calendars,
            benchmark_id=prepared['spy_id'],fixed_horizon=HORIZON,cost_per_side=cost/2,review_requested=day in outputs)
        if state['equity'] is None or any(o['execute_on']<=day for o in state['orders']):
            issues.append({'date':day,'reason':'missing_exact_execution_or_valuation'});break
        curve.append({'date':day,'equity':state['equity'],'benchmark':state['benchmark_value']})
    return dict(state=state,curve=curve,issues=issues)


def metrics(simulation,baseline=None):
    state=simulation['state'];curve=simulation['curve']
    if not state or not curve:return {'complete':False,'weeks':0}
    # Non-overlapping five-session account returns, not four overlapping bets
    # each borrowing the full capital. All accounts remain capped at ten stocks.
    points=curve[::5]
    if points[-1]!=curve[-1]:points.append(curve[-1])
    points=[p for p in points if p['benchmark'] is not None]
    changes=[b['equity']/a['equity']-1 for a,b in zip(points,points[1:])]
    spy=[b['benchmark']/a['benchmark']-1 for a,b in zip(points,points[1:])]
    base_map={p['date']:p for p in (baseline or {}).get('curve',[])}
    paired=[(b['equity']/a['equity']-1)-(base_map[b['date']]['equity']/base_map[a['date']]['equity']-1)
        for a,b in zip(points,points[1:]) if a['date'] in base_map and b['date'] in base_map]
    benchmark=state.get('benchmark_value')
    return dict(complete=not simulation['issues'] and state.get('metric_history_complete',True),weeks=len(changes),
        net_return=state['equity']/INITIAL_CASH-1,excess_vs_spy=state['equity']/INITIAL_CASH-benchmark/INITIAL_CASH if benchmark else None,
        lower_bound_vs_spy=block_lower_bound([a-b for a,b in zip(changes,spy)]),
        lower_bound_vs_base=block_lower_bound(paired) if paired else None,
        max_drawdown=state['max_drawdown'] if state.get('metric_history_complete',True) else None,
        trading_costs=state['costs'],turnover=state['traded_notional']/INITIAL_CASH,completed_positions=state['completed_trades'])


def validate(prepared,walker=None):
    walker=walker or walk_forward;records=prepared['records']
    dates=sorted({r['date'] for r in records if r['label_end_date'] and r['label_end_date']<=prepared['latest_date']})
    report=dict(evaluation_protocol=PROTOCOL,model_version=VERSION,primary_horizon_days=20,max_positions=10,
        round_trip_cost=.002,stress_round_trip_cost=.005,minimum_mature_dates=MIN_MATURE_DATES,
        matured_dates=len(dates),minimum_training_rows=MIN_ROWS,stages={},promotion_passed=False,
        active_selection_changed=False,limitations=['Research only; sector classifications are current.',
            'Historical earnings risk gates and corporate-action-adjusted total returns are not fully replayed.',
            'Stored exact closes proxy execution; taxes and dividends are excluded.'])
    if len(dates)<MIN_MATURE_DATES:
        report.update(outcome='insufficient_history',blocked_reason='insufficient_matured_point_in_time_dates');return report
    first=int(len(dates)*.6);second=int(len(dates)*.8);holdout=dates[second:]
    ends={r['date']:r['label_end_date'] for r in records if r['label_end_date']}
    selection=[d for d in dates[first:second] if ends[d]<holdout[0]]
    report.update(selection_start=selection[0] if selection else None,holdout_start=holdout[0],
        selection_last_exit=max((ends[d] for d in selection),default=None))
    if len(selection)<MIN_AUDIT_WEEKS or len(holdout)<MIN_AUDIT_WEEKS:
        report.update(outcome='insufficient_history',blocked_reason='insufficient_purged_selection_or_holdout_dates');return report
    outputs={};simulations={}
    for family in ('price_context',)+FAMILIES:
        try:
            out,sizes=walker(records,selection,family)
            simulation=simulate(out,prepared);outputs[family]=out;simulations[family]=simulation
            report['stages'][family]={'status':'evaluated','training':sizes,'selection':metrics(simulation,simulations.get('price_context'))}
        except RuntimeError as exc:
            report['stages'][family]={'status':'blocked','reason':str(exc)}
    if 'price_context' not in simulations:
        report.update(outcome='insufficient_history',blocked_reason='baseline_training_unavailable');return report
    eligible=[f for f in simulations if report['stages'][f]['selection']['complete']]
    winner=max(eligible,key=lambda f:report['stages'][f]['selection']['net_return'],default='price_context')
    # Freeze the winning family BEFORE fitting/predicting the final audit period.
    report['selected_family']=winner
    audits={}
    for family in set(('price_context',winner)):
        out,_=walker(records,holdout,family);audits[family]=simulate(out,prepared)
        if family==winner:
            report['stress_holdout']=metrics(simulate(out,prepared,cost=.005))
    report['holdout']=metrics(audits[winner],audits['price_context'])
    report['base_holdout']=metrics(audits['price_context'])
    m=report['holdout'];stress=report['stress_holdout'];base=report['base_holdout']
    report['statistical_gates_passed']=bool(m['complete'] and m['weeks']>=26 and m['net_return']>0 and
        (m.get('lower_bound_vs_spy') or -1)>0 and (stress.get('excess_vs_spy') or -1)>0 and
        m.get('max_drawdown') is not None and base.get('max_drawdown') is not None and m['max_drawdown']>=base['max_drawdown'] and
        (winner=='price_context' or (m.get('lower_bound_vs_base') or -1)>0))
    report['outcome']='research_evaluated'
    # Promotion deliberately requires a separately reviewed deployment protocol.
    return report


def prepare(db,years=5):
    from .prospective_metrics import paged
    prep=_prepare(db,years)
    macro=paged(db.table('macro_observations').select('id,series_id,observation_date,value,units,source,vintage_date,observed_at').order('id'))
    return prepared_records(prep,macro)
