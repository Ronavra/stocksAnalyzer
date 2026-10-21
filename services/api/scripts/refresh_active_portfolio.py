"""Persist one atomic paper-portfolio decision per New York calendar day."""
import argparse
import json
import sys
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from dotenv import load_dotenv

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR)); load_dotenv(API_DIR/'.env')
from app.db.client import get_supabase
from app.market_calendar import NY, latest_completed_session
from app.research.active_portfolio import POLICY, advance, load_active_portfolio
from app.research.earnings_catalysts import recent_earnings, upcoming_earnings
from app.research.financial_ranking import load_inputs, rank_candidates
from scripts.generate_weekly_signals import current_candidates


def refresh(db, now=None, dry_run=False):
    now=now or datetime.now(timezone.utc)
    today=now.astimezone(NY).date().isoformat()
    previous=load_active_portfolio(db)
    revision=previous.get('revision',0)
    rows=db.rpc('research_dashboard_candidates').execute().data or []
    asof,current=current_candidates(rows)
    expected=latest_completed_session(now.astimezone(NY)).isoformat()
    if not current or asof != expected:
        raise RuntimeError(f'Active portfolio requires current prices/features for {expected}; received {asof}')
    if (previous.get('decision_day') == today and (previous.get('portfolio') or {}).get('as_of_date')==asof
            and not (previous.get('portfolio') or {}).get('ranking_error') and not dry_run):
        return dict(status='already_recorded', revision=revision)
    # Include held companies even if they left the universe or lost their setup.
    accounts=[previous.get('portfolio') or {},*(previous.get('experiments') or {}).values()]
    held=[p for account in accounts for p in account.get('positions',[])]
    all_rows={r['company_id']:r for r in current}
    for p in held:
        all_rows.setdefault(p['company_id'],dict(company_id=p['company_id'],price_date=asof))
    calendars=upcoming_earnings(db,list(all_rows.values()),today,now.isoformat())
    error=None; summary={}; picks=[]
    try:
        inputs=load_inputs(db,asof)
        picks,summary=rank_candidates(current,inputs,asof,recent_earnings(db,current),top=None,
            upcoming=calendars,primary_horizon=20,include_rejections=True,now=now)
    except RuntimeError as exc:
        # Still mark/fill already decided paper orders and surface held-stock risks.
        error=str(exc)
    candidates=[dict(company_id=p['row']['company_id'],ticker=p['row']['ticker'],score=p['score'],
                     sector=inputs['companies'][p['row']['company_id']].get('sector')) for p in picks]
    ids=sorted(set(all_rows)|{r['company_id'] for account in accounts for r in account.get('orders',[])})
    spy=db.table('companies').select('id').eq('ticker','SPY').limit(1).execute().data or []
    benchmark_id=spy[0]['id'] if spy else None
    if benchmark_id is not None:
        ids.append(benchmark_id)
    since=(date.fromisoformat(asof)-timedelta(days=130)).isoformat()
    # Pending fills must remain resolvable even after a prolonged outage.
    order_dates=[o['execute_on'] for account in accounts for o in account.get('orders',[])]
    order_dates += [account['benchmark_on'] for account in accounts if account.get('benchmark_on')]
    if order_dates:
        since=min(since,min(order_dates))
    prices=db.rpc('active_portfolio_price_window',dict(p_since=since,p_until=asof,p_company_ids=ids)).execute().data or []
    state=advance(previous.get('portfolio'),candidates,prices,asof,now,calendars,
                  summary.get('company_rejections'),error,benchmark_id)
    experiments={str(h):advance((previous.get('experiments') or {}).get(str(h)),candidates,prices,asof,now,calendars,
        summary.get('company_rejections'),error,benchmark_id,fixed_horizon=h) for h in (5,10,20)}
    snapshot=dict(decision_day=today,portfolio=state,experiments=experiments,ranking=dict(policy_version=summary.get('policy_version'),
        weights=summary.get('weights'),eligible=len(candidates),primary_horizon_days=20,
        note='Existing five-day price-setup factors reused; twenty-day predictive value is unvalidated.'),
        status_detail='research_unavailable' if error else 'observed',
        limitations=['Paper account; no brokerage connection or actual holdings recorded.',
                     'Close-price execution proxy and assumed 0.10% per side; excludes taxes and dividends.',
                     'Twenty sessions is a review target, not a proven optimal holding period.',
                     'Forward experiments use the same twenty-day-screened candidate pool and fixed exits at 5/10/20 sessions, with earlier risk exits. They do not validate new horizon-specific forecasts.',
                     'Unknown or stale data pauses new decisions; it does not establish that a stock is safe.'])
    if dry_run:
        return dict(status='preview',snapshot=snapshot)
    result=db.rpc('record_active_portfolio',dict(p_expected_revision=revision,p_snapshot=snapshot)).execute().data
    if not isinstance(result,dict) or result.get('status') not in ('recorded','already_recorded'):
        raise RuntimeError(f'Portfolio snapshot not recorded: {result}')
    return dict(**result,positions=len(state['positions']),pending_orders=len(state['orders']),
                eligible=len(candidates),research_error=error)


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--dry-run',action='store_true'); args=parser.parse_args()
    result=refresh(get_supabase(),dry_run=args.dry_run)
    print(json.dumps(result,indent=2),flush=True)
    if result.get('research_error'):
        raise RuntimeError('Portfolio marks recorded, but research is unavailable; inspect snapshot alerts')

if __name__=='__main__':
    main()
