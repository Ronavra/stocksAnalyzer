"""Read-only smoke check of production API payloads after history repair."""
import json
import sys
from pathlib import Path

API_DIR=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(API_DIR))
from app.main import ready
from app.routers.research import data_audit,candidates,cohorts,signals,scorecard,system_health

def main():
    assert ready()=={'status':'ready','database':'connected'},'Database readiness failed'
    audit=data_audit()
    assert audit['universe']>=500,'Unexpected universe coverage'
    rows=candidates()
    groups=cohorts()
    predictions=signals()
    results=scorecard()
    health=system_health()
    assert health['market_data_current'],'Market close/features are not current'
    assert results['prospective']['sample_unit']=='weekly_cohort'
    for row in predictions:
        assert row['recommendation_price'] is not None,'Missing frozen recommendation close'
        assert row['current_price'] is not None,'Missing current price'
    report={'universe':audit['universe'],'candidates':len(rows),'cohorts':len(groups),
            'signals':len(predictions),'latest_price_date':health['latest_price_date'],
            'market_data_current':health['market_data_current'],'layers':audit['layers'],
            'active_policy':results['prospective']['active_version'],
            'prospective':results['prospective'],'financial_quality':audit.get('financial_quality')}
    (API_DIR/'research_release_verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('prospective','financial_quality')},indent=2))

if __name__=='__main__': main()
