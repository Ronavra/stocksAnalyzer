"""Policy-specific, equal-weight cohort results from frozen live decisions."""
from statistics import mean
from .price_window import canonical_prices
from .financial_ranking import SIGNAL_VERSION


def prospective_metrics(cohorts, predictions, market_prices):
    market = {p['price_date']: float(p['close']) for p in canonical_prices(market_prices) if p.get('close')}
    calendar = sorted(market)
    versions = sorted({c['model_version'] for c in cohorts} | {p['model_version'] for p in predictions})
    result = {}
    for version in versions:
        groups = [c for c in cohorts if c['model_version'] == version]
        by_horizon = {}
        for horizon in (5, 10, 20):
            outcomes = []
            for cohort in groups:
                if horizon not in cohort['horizons']:
                    continue
                rows = [p for p in predictions if p['signal_date'] == cohort['signal_date']
                        and p['model_version'] == version and p['horizon_days'] == horizon]
                if cohort['expected_picks']:
                    if len(rows) != cohort['expected_picks'] or any(p.get('evaluated_at') is None
                        or p.get('actual_return') is None or p.get('excess_return') is None for p in rows):
                        continue
                    outcomes.append({'date': cohort['signal_date'], 'return': mean(float(p['actual_return']) for p in rows),
                                     'excess': mean(float(p['excess_return']) for p in rows), 'cash': False})
                else:
                    sessions = [d for d in calendar if d > cohort['signal_date']]
                    if len(sessions) <= horizon:
                        continue
                    benchmark = market[sessions[horizon]] / market[sessions[0]] - 1
                    outcomes.append({'date': cohort['signal_date'], 'return': 0., 'excess': -benchmark, 'cash': True})
            by_horizon[str(horizon)] = {
                'published_cohorts': sum(horizon in c['horizons'] for c in groups),
                'evaluated_cohorts': len(outcomes), 'cash_cohorts': sum(x['cash'] for x in outcomes),
                'mean_net_return': mean(x['return'] for x in outcomes) if outcomes else None,
                'mean_excess_return': mean(x['excess'] for x in outcomes) if outcomes else None,
                'positive_cohort_rate': mean(x['return'] > 0 for x in outcomes) if outcomes else None,
                'beat_spy_cohort_rate': mean(x['excess'] > 0 for x in outcomes) if outcomes else None,
                'outcomes': outcomes,
            }
        result[version] = {'cohorts': len(groups), 'no_pick_cohorts': sum(c['expected_picks'] == 0 for c in groups),
                           'by_horizon': by_horizon, 'validated_forecast': False}
    result.setdefault(SIGNAL_VERSION, {'cohorts': 0, 'no_pick_cohorts': 0, 'by_horizon': {}, 'validated_forecast': False})
    return {'active_version': SIGNAL_VERSION, 'by_policy': result,
            'sample_unit': 'weekly_cohort', 'overlapping_windows': True,
            'note': 'Observed live results, separated by frozen policy. No promotion or statistical independence is implied.'}


def paged(query, size=1000):
    rows = []
    offset = 0
    while True:
        page = query.range(offset, offset+size-1).execute().data or []
        rows.extend(page)
        if len(page) < size:
            return rows
        offset += size
