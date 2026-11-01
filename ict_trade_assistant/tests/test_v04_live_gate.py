"""合成链与资格接口契约测试，不是实时资格验收。"""
from copy import deepcopy
from datetime import timedelta
import pytest
from desk.decision import decision
from desk.ict_v03 import scan
from test_ict_v03 import history, at
from test_decision_v04 import observation


def inputs():
    now=at(14,32)
    report=scan('US.SPY',history(),now)
    obs=observation(now)
    obs.update(mode='LIVE',health=dict(quality='AVAILABLE',price=104.,right='LV3',quote_at=now.isoformat(),source='SYNTHETIC_TEST_ONLY'))
    return now,obs,report


@pytest.mark.parametrize('asserted_qualified',[False,True])
def test_history_ce_with_fresh_quote_cannot_authorize_review(asserted_qualified):
    now,obs,report=inputs()
    if asserted_qualified:
        report.update(live_qualification='PASSED',qualified=True,live_alerts_enabled=True)
        obs['ict_qualified']=True
    before=deepcopy(report)
    result=decision('US.SPY',obs,report,now)
    assert result['stage']=='CE_REVIEW' and result['linked'] and result['qualification']==0
    assert not result['live_review']
    assert '人工风险与执行审查' not in result['allowed']
    assert report==before


def future_contract():
    from desk.decision import structure
    now,obs,report=inputs()
    report['mode']='LIVE_OBSERVATION'
    for event in report['events']:event['source']='FUTU_OPEND'
    s=structure(report,now)
    report['ict_live_evidence']=dict(
        **{k:report[k] for k in ('symbol','timeframe','version','parameter_version')},
        structure_realtime_confirmed=True,arrival_times_verified=True,rth_acceptance='PASSED',
        acceptance_evidence_id='SYNTHETIC_CONTRACT_TEST_ONLY',verified_at=now.isoformat(),
        valid_until=(now+timedelta(minutes=1)).isoformat(),
        received_at_by_event={e['id']:e['confirmed_at'] for e in s['evidence']})
    return now,obs,report,s


def test_future_positive_contract_is_not_v04_authorization():
    from desk.ict_live_gate import check_future_evidence_contract,ict_live_qualification
    now,obs,report,s=future_contract()
    assert check_future_evidence_contract(report,s,now)
    gate=ict_live_qualification(report,s,now)
    assert gate['contract_passed'] and not gate['qualified']
    result=decision('US.SPY',obs,report,now)
    assert result['price_live_qualified'] and not result['live_review']
    assert '人工风险与执行审查' not in result['allowed']


@pytest.mark.parametrize('damage',['history','arrival_missing','arrival_future','rth','version','expired','source','confirmed'])
def test_future_contract_fails_closed(damage):
    from desk.ict_live_gate import check_future_evidence_contract
    now,obs,report,s=future_contract();proof=report['ict_live_evidence']
    if damage=='history':report['mode']='HISTORICAL_OBSERVATION'
    elif damage=='arrival_missing':proof['received_at_by_event'].pop(s['evidence'][0]['id'])
    elif damage=='arrival_future':proof['received_at_by_event'][s['evidence'][0]['id']]=(now+timedelta(days=1)).isoformat()
    elif damage=='rth':proof['rth_acceptance']='PENDING'
    elif damage=='version':proof['parameter_version']='wrong'
    elif damage=='expired':proof['valid_until']=(now-timedelta(seconds=1)).isoformat()
    elif damage=='source':s['evidence'][0]['source']='SYNTHETIC_TEST_ONLY'
    elif damage=='confirmed':proof['structure_realtime_confirmed']=False
    assert not check_future_evidence_contract(report,s,now)
