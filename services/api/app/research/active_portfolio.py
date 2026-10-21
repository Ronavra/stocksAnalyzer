"""One persistent, funded paper portfolio. Decisions never use a past close as a fill."""
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from statistics import correlation

from ..market_calendar import NY, is_trading_day, session_close
from .price_window import canonical_prices

POLICY = 'active-ten-v1'
CONFIG = dict(max_positions=10, holding_sessions=20, entry_weight=.10, sector_weight=.30,
              replacement_margin=5., max_weekly_replacements=2, max_correlation=.85,
              minimum_correlation_observations=40, one_way_cost=.001)
INITIAL_CASH = 100000.


def sessions_after(day, count=1):
    day = date.fromisoformat(str(day))
    while count:
        day += timedelta(days=1)
        if is_trading_day(day):
            count -= 1
    return day.isoformat()


def positive(value):
    try:
        value = float(value)
        return value if isfinite(value) and value > 0 else None
    except (ValueError, TypeError):
        return None


def initial_state():
    return dict(policy=POLICY, mode='paper', cash=INITIAL_CASH, positions=[], orders=[],
                costs=0., traded_notional=0., last_review_week=None, peak_equity=INITIAL_CASH,
                max_drawdown=0., completed_trades=0, benchmark_units=None, started_at=None, fills=[], actions=[], alerts=[])


def price_maps(rows):
    result = defaultdict(dict)
    for row in canonical_prices(rows):
        price = positive(row.get('close'))
        if price:
            result[row['company_id']][row['price_date']] = price
    return result


def pair_correlation(a, b, until):
    # Adjacent observations must be exact exchange sessions for both stocks.
    returns = []
    for day in sorted(set(a) & set(b)):
        if day > until:
            continue
        prev = date.fromisoformat(day)-timedelta(days=1)
        while not is_trading_day(prev):
            prev -= timedelta(days=1)
        prev = prev.isoformat()
        if prev in a and prev in b:
            returns.append((a[day]/a[prev]-1, b[day]/b[prev]-1))
    returns = returns[-60:]
    if len(returns) < CONFIG['minimum_correlation_observations']:
        return None
    try:
        return correlation(*zip(*returns))
    except (ValueError, ArithmeticError):
        return None


def advance(previous, candidates, prices, asof, now=None, calendars=None, rejections=None,
            ranking_error=None, benchmark_id=None, fixed_horizon=None):
    """Daily marks/fills, weekly rotation and 20-session thesis reviews.

    Missing research causes a review alert, never an automatic sale. Actual
    earnings and confirmed score failures can override the routine rotation cap.
    """
    if fixed_horizon not in (None,5,10,20):
        raise ValueError('Unsupported experimental horizon')
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(NY).date().isoformat()
    if asof > today or session_close(date.fromisoformat(asof)) > now:
        raise ValueError('Cannot mark a future or unfinished market session')
    state = deepcopy(previous or initial_state())
    if state.get('policy') != POLICY or state.get('mode') != 'paper':
        raise ValueError('Unsupported portfolio state')
    if state.get('as_of_date', '') > asof:
        raise ValueError('Market date moved backwards')
    maps = price_maps(prices)
    calendars = calendars or {}
    rejections = rejections or {}
    state.update(actions=[], alerts=[], fills=[])
    state['started_at'] = state.get('started_at') or now.isoformat()
    positions = {p['company_id']: p for p in state['positions']}
    if len(positions) != len(state['positions']) or len(positions) > 10:
        raise ValueError('Invalid or duplicate positions')
    pending = []
    # Sell first at each execution close. Never substitute today's price for a
    # missing historical execution close; an unresolved order remains flagged.
    for order in sorted(state['orders'], key=lambda o:(o['execute_on'], o['side'] != 'sell', o['company_id'])):
        cid = order['company_id']; execution = order['execute_on']
        if execution > asof:
            pending.append(order); continue
        quote = maps[cid].get(execution)
        if quote is None:
            pending.append(order)
            state['alerts'].append(f'{order["ticker"]}: missing execution close {execution}; order unresolved')
            continue
        if order['side'] == 'sell':
            p = positions.get(cid)
            if p is None:
                continue
            notional = p['shares']*quote
            fee = notional*CONFIG['one_way_cost']
            state['cash'] += notional-fee
            del positions[cid]
            state['completed_trades'] = state.get('completed_trades',0)+1
        else:
            if cid in positions:
                continue
            if len(positions) >= CONFIG['max_positions']:
                state['alerts'].append(f'{order["ticker"]}: entry cancelled; no free position')
                continue
            # Recheck position/sector limits at the execution close, including
            # overnight price moves. Missing marks block entry rather than guess.
            if any(maps[p['company_id']].get(execution) is None for p in positions.values()):
                state['alerts'].append(f'{order["ticker"]}: entry cancelled; execution marks incomplete')
                continue
            nav = state['cash'] + sum(p['shares']*maps[p['company_id']][execution] for p in positions.values())
            sector_value = sum(p['shares']*maps[p['company_id']][execution] for p in positions.values() if p['sector']==order['sector'])
            budget = min(order['budget'], state['cash'], nav*CONFIG['entry_weight'],
                         max(0., nav*CONFIG['sector_weight']-sector_value))
            if budget <= 1e-6:
                continue
            notional = budget/(1+CONFIG['one_way_cost']); fee = budget-notional
            state['cash'] -= budget
            positions[cid] = dict(company_id=cid, ticker=order['ticker'], sector=order['sector'],
                                  shares=notional/quote, entry_price=quote, entry_date=execution,
                                  review_due=sessions_after(execution, CONFIG['holding_sessions']),
                                  entry_score=order['score'], score=order['score'])
        state['costs'] += fee
        state['traded_notional'] += notional
        state['fills'].append(dict(**order, fill_price=quote, fee=fee, notional=notional))
    state['orders'] = pending
    missing = [p['ticker'] for p in positions.values() if maps[p['company_id']].get(asof) is None]
    marks = {cid:maps[cid].get(asof) for cid in positions}
    if missing:
        state['alerts'].append('Current marks missing: '+', '.join(missing)+'; new decisions paused')
    equity = None if missing else state['cash']+sum(p['shares']*marks[cid] for cid,p in positions.items())
    state.update(as_of_date=asof, decision_at=now.isoformat(), equity=equity, config=dict(CONFIG),
                 validated=False, ranking_error=ranking_error)
    if equity is not None:
        state['peak_equity'] = max(state['peak_equity'], equity)
        state['max_drawdown'] = min(state['max_drawdown'], equity/state['peak_equity']-1)
    state['benchmark_on'] = state.get('benchmark_on') or sessions_after(today)
    if benchmark_id is not None:
        entry_quote = maps[benchmark_id].get(state['benchmark_on'])
        quote = maps[benchmark_id].get(asof)
        if entry_quote and state['benchmark_on'] <= asof and state['benchmark_units'] is None:
            state['benchmark_units'] = INITIAL_CASH/entry_quote
        state['benchmark_value'] = state['benchmark_units']*quote if quote and state['benchmark_units'] else INITIAL_CASH if asof < state['benchmark_on'] else None
    for cid,p in positions.items():
        p.update(current_price=marks[cid], price_date=asof if marks[cid] else None,
                 market_value=p['shares']*marks[cid] if marks[cid] else None,
                 weight=p['shares']*marks[cid]/equity if marks[cid] and equity else None)
        if p['weight'] is not None and p['weight'] > CONFIG['entry_weight']+.005:
            state['alerts'].append(f'{p["ticker"]}: position weight above entry target; review concentration')
    candidate_map = {p['company_id']:p for p in candidates}
    next_execution = sessions_after(max(asof,today))
    week = (date.fromisoformat(today)-timedelta(days=date.fromisoformat(today).weekday())).isoformat()
    weekly = state['last_review_week'] != week
    unresolved = any(o['execute_on'] <= asof for o in pending)
    can_decide = equity is not None and not unresolved and not ranking_error
    selling = {o['company_id'] for o in pending if o['side']=='sell' and o['execute_on'] <= next_execution}

    def sell(p, reason):
        cid=p['company_id']
        if cid not in selling:
            state['orders'] = [o for o in state['orders'] if not (o['company_id']==cid and o['side']=='sell')]
            state['orders'].append(dict(side='sell', company_id=cid, ticker=p['ticker'],
                                        execute_on=next_execution, reason=reason, decided_at=now.isoformat()))
            selling.add(cid)

    for cid,p in positions.items():
        candidate = candidate_map.get(cid)
        p['score'] = candidate['score'] if candidate else None
        calendar = calendars.get(cid) or {}
        event = calendar.get('reported_date')
        if calendar.get('calendar_status') != 'current':
            state['alerts'].append(f'{p["ticker"]}: earnings calendar unknown; manual review required')
        if event and calendar.get('calendar_status') == 'current' and event <= sessions_after(next_execution):
            sell(p, 'earnings_approaching')
            if event <= next_execution:
                state['alerts'].append(f'{p["ticker"]}: earnings may precede the next executable close')
        elif can_decide and (weekly or p['review_due'] <= asof):
            rejection = rejections.get(str(cid)) or rejections.get(cid)
            if rejection in ('financial_score_below_minimum','combined_score_below_minimum'):
                sell(p, rejection)
            elif candidate:
                if not fixed_horizon and p['review_due'] <= asof:
                    p['review_due'] = sessions_after(asof, CONFIG['holding_sessions'])
                    state['actions'].append(dict(ticker=p['ticker'], action='hold', reason='thesis_renewed', review_due=p['review_due']))
            else:
                state['alerts'].append(f'{p["ticker"]}: research eligibility needs review ({rejection or ranking_error or "not currently eligible"})')
    # Routine replacements only on the weekly review and only by a meaningful
    # score margin. A score is not a predicted return or probability.
    replacements = 0
    if can_decide and weekly:
        selected = {cid:p for cid,p in positions.items() if cid not in selling}
        for order in state['orders']:
            if order['side']=='buy':
                selected[order['company_id']] = order
        sector_values = defaultdict(float)
        for cid,p in selected.items():
            sector_values[p['sector']] += p.get('market_value', p.get('budget',0.)) or 0.
        committed = sum(o.get('budget',0.) for o in state['orders'] if o['side']=='buy')
        spendable = max(0.,state['cash']-committed)+sum(positions[cid]['market_value']*(1-CONFIG['one_way_cost']) for cid in selling if positions[cid].get('market_value'))
        for c in sorted(candidates,key=lambda p:(-p['score'],str(p['company_id']))):
            cid = c['company_id']; sector = c.get('sector') or 'Unknown'
            if cid in selected or cid in positions or sector == 'Unknown':
                continue
            weak = None
            if len(selected) >= CONFIG['max_positions']:
                eligible = [p for p in selected.values() if p['company_id'] in positions and p.get('score') is not None]
                weak = min(eligible,key=lambda p:(p['score'],str(p['company_id'])),default=None)
                if fixed_horizon or replacements >= CONFIG['max_weekly_replacements'] or not weak or c['score'] < weak['score']+CONFIG['replacement_margin']:
                    continue
            other_ids = set(selected)-({weak['company_id']} if weak else set())
            correlations = [pair_correlation(maps[cid],maps[other],asof) for other in other_ids]
            if any(r is None or r >= CONFIG['max_correlation'] for r in correlations):
                continue
            removed = weak.get('market_value',0.) if weak else 0.
            sector_removed = removed if weak and weak['sector']==sector else 0.
            budget = min(equity*CONFIG['entry_weight'], max(0.,equity*CONFIG['sector_weight']-sector_values[sector]+sector_removed), spendable+removed*(1-CONFIG['one_way_cost']))
            if budget <= equity*.001:
                continue
            if weak:
                sell(weak,'stronger_candidate')
                del selected[weak['company_id']]
                sector_values[weak['sector']] -= removed
                spendable += removed*(1-CONFIG['one_way_cost'])
                replacements += 1
            order = dict(side='buy', company_id=cid, ticker=c['ticker'], sector=sector, score=c['score'],
                         budget=budget, execute_on=next_execution, reason='stronger_candidate' if weak else 'free_slot',
                         decided_at=now.isoformat())
            state['orders'].append(order); selected[cid] = order
            if fixed_horizon:
                state['orders'].append(dict(side='sell', company_id=cid, ticker=c['ticker'],
                    execute_on=sessions_after(next_execution,fixed_horizon), reason='fixed_holding_period', decided_at=now.isoformat()))
            sector_values[sector] += budget; spendable -= budget
        state['last_review_week'] = week
    if ranking_error:
        state['alerts'].append('Research unavailable; entries and routine replacements paused: '+ranking_error)
    state['fixed_horizon'] = fixed_horizon
    state['positions'] = sorted(positions.values(),key=lambda p:p['ticker'])
    for p in state['positions']:
        state['actions'].append(dict(ticker=p['ticker'], action='exit' if p['company_id'] in selling else 'review' if p['score'] is None else 'hold',
                                     reason=next((o['reason'] for o in state['orders'] if o['company_id']==p['company_id'] and o['side']=='sell'),'current_thesis' if p['score'] is not None else 'data_or_eligibility_review'), review_due=p['review_due']))
    state['cash_weight'] = state['cash']/equity if equity else None
    sectors=defaultdict(float)
    for p in state['positions']:
        sectors[p['sector']] += p['weight'] or 0.
    for sector,weight in sectors.items():
        if weight > CONFIG['sector_weight']+.005:
            state['alerts'].append(f'{sector}: sector weight exceeds 30%; review concentration')
    state['sector_weights'] = dict(sectors)
    state['alerts'] = list(dict.fromkeys(state['alerts']))
    if state['cash'] < -1e-6 or len(state['positions']) > 10:
        raise ValueError('Portfolio funding/position constraint failed')
    return state


def load_active_portfolio(db):
    rows = (db.table('active_portfolio_snapshots').select('id,created_at,snapshot')
            .eq('policy',POLICY).order('id',desc=True).limit(1).execute().data or [])
    if not rows:
        return dict(status='pending', policy=POLICY, mode='paper', config=dict(CONFIG), validated=False)
    row=rows[0]
    return dict(status='ok', revision=row['id'], recorded_at=row['created_at'], **row['snapshot'])
