"""定向审查回归；完整链为合成数据，不代表真实市场验收。"""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from desk.decision import decision, prioritize, structure, deadline
from desk.ict_v03 import scan
from desk.store import Store
from test_ict_v03 import history, at
from test_decision_v04 import observation


@pytest.mark.parametrize('case',['invalidated_chain','expired_chain','invalidated_fvg'])
def test_inactive_structure_is_history_only(case):
    now=at(16,2) if case=='invalidated_chain' else at(12,32)
    report=scan('US.SPY',history(),now)
    if case!='invalidated_fvg':
        report['fvgs']=[]
        if case=='expired_chain':now=pd.Timestamp(deadline(now,6))+pd.Timedelta(seconds=1)
    else:
        report['events']=[]
        report['fvgs']=[dict(report['fvgs'][-1],setup_id=None,status='INVALIDATED',invalidation_reason='合成失效原因')]
    before=deepcopy(report)
    result=decision('US.SPY',observation(now),report,now)
    assert result['stage']=='INVALIDATED' and result['evidence'] and result['invalid_condition']
    assert all(r['key']!=result['structure']['event_id'] for r in result['regions'])
    assert result['focus']['key']=='PDL'
    assert result['next_region'] is None
    assert report==before


@pytest.mark.parametrize('same_symbol',[False,True])
def test_independent_fvg_below_confirmed_sweep(same_symbol):
    now=at(12,32)
    linked=scan('US.SPY',history(),at(10,32));linked['fvgs']=[]
    independent=scan('US.QQQ',history(),now);independent['events']=[]
    independent['fvgs']=[dict(independent['fvgs'][-1],setup_id=None)]
    if same_symbol:
        linked['fvgs']=independent['fvgs']
        assert structure(linked,now)['stage']=='SWEEP_CONFIRMED'
    else:
        obs={s:observation(now,s) for s in ['US.SPY','US.QQQ']}
        rows=prioritize(obs,{'US.SPY':linked,'US.QQQ':independent},now)
        assert rows[0]['symbol']=='US.SPY'
        assert rows[1]['stage']=='FVG_CONFIRMED' and not rows[1]['linked']


def test_outside_candidate_is_not_labelled_near(tmp_path,market_fixture):
    now=pd.Timestamp('2026-10-30T10:10',tz='America/New_York').to_pydatetime()
    report=scan('US.SPY',history(),at(12,32));report['events']=[]
    report['fvgs']=[dict(report['fvgs'][-1],setup_id=None,low=120.,high=121.,ce=120.5)]
    store=Store(tmp_path/'isolated.sqlite3')
    with patch('desk.store.Store',return_value=store),patch('desk.provider.Provider.fetch',return_value=market_fixture),patch('desk.workspace.now_et',return_value=now),patch('desk.workspace.historical_ict',return_value=report):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
        assert not app.exception
        labels=[b.label for b in app.button if '历史结构区域' in b.label]
        assert labels and all('区域外' in label and '接近关键价' not in label for label in labels)


@pytest.mark.parametrize('low,high,label',[(99.,101.,'区域内'),(100.5,101.,'接近关键价')])
def test_price_region_labels(tmp_path,market_fixture,low,high,label):
    now=pd.Timestamp('2026-10-30T10:10',tz='America/New_York').to_pydatetime()
    store=Store(tmp_path/'isolated.sqlite3')
    store.save('zones',{'US.SPY':dict(low=low,high=high,direction='LONG')})
    report=dict(status='AVAILABLE',timeframe='1H',events=[],fvgs=[],sweeps=[],reason='合成无结构')
    with patch('desk.store.Store',return_value=store),patch('desk.provider.Provider.fetch',return_value=market_fixture),patch('desk.workspace.now_et',return_value=now),patch('desk.workspace.historical_ict',return_value=report):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
        assert not app.exception
        buttons=[b for b in app.button if (b.key or '').startswith('pick_US.SPY_')]
        assert len(buttons)==1 and buttons[0].label.endswith(label)
