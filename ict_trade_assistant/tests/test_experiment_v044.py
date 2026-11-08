from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
import sqlite3

import pandas as pd
import pytest

from desk.clock import CAL, ET
from desk.experiment import BASELINE, Experiment, ExperimentStore, completed_snapshot, distance_result, replay_cutoff
from desk.market_state import market_state


@pytest.mark.parametrize('values', [dict(ema_short=4), dict(ema_long=51), dict(atr_period=6),
    dict(sideways_atr=.09), dict(candidate_atr=1.01), dict(ema_short=20.0),
    dict(ema_short=True), dict(sideways_atr=float('nan'))])
def test_input_validation(values):
    with pytest.raises(ValueError):
        Experiment(**values)


def test_separate_versioned_store_and_immutable_baseline(tmp_path):
    path = tmp_path/'experiments.sqlite3'
    store = ExperimentStore(path)
    assert store.names() == ['Baseline'] and not path.exists()
    for name in ('Baseline', ' baseline ', ''):
        with pytest.raises(ValueError):
            store.save(name, replace(BASELINE, ema_short=5))
    config = replace(BASELINE, ema_short=5, ema_long=35, atr_period=20, sideways_atr=1.5, candidate_atr=1.)
    store.save('灵敏观察', config)
    reopened = ExperimentStore(path)
    assert reopened.load('灵敏观察') == config
    assert reopened.load('Baseline') == BASELINE
    with sqlite3.connect(path) as connection:
        version, payload = connection.execute('SELECT version,parameters FROM experiments').fetchone()
        assert version == 'v0.4.4.1' and json.loads(payload) == asdict(config)
        assert connection.execute("SELECT count(*) FROM sqlite_master WHERE name='settings'").fetchone()[0] == 0


def test_replay_early_close_dst_and_non_session():
    assert replay_cutoff(datetime(2026,11,27).date()).isoformat() == '2026-11-27T13:02:00-05:00'
    assert replay_cutoff(datetime(2026,10,29).date()).utcoffset() == timedelta(hours=-4)
    assert replay_cutoff(datetime(2026,11,2).date()).utcoffset() == timedelta(hours=-5)
    with pytest.raises(ValueError, match='不是纽约交易日'):
        replay_cutoff(datetime(2026,11,7).date())


def sample():
    ts = CAL.sessions_in_range('2026-07-01','2026-10-29')[-60:]
    dates = pd.DatetimeIndex(ts.tz_localize(None)).tz_localize(ET)
    close = pd.Series([100 + i*.1 + (i%5)*.2 for i in range(60)])
    return pd.DataFrame(dict(ts=dates, open=close, high=close+1, low=close-1, close=close,
                             eligible=True, session='RTH', source='TEST_SAME_SOURCE'))


def test_cutoff_poison_ineligible_and_short_samples():
    frame = sample()
    cutoff = replay_cutoff(frame.ts.iloc[-2].date())
    poisoned = frame.copy()
    poisoned.loc[poisoned.index[-1], ['open','high','low','close']] = 999999.
    a, chart = market_state(frame, '1D', cutoff, 'TEST')
    b, other = market_state(poisoned, '1D', cutoff, 'TEST')
    assert a == b
    pd.testing.assert_frame_equal(chart, other)
    assert (chart.closed_at + timedelta(minutes=2) <= cutoff).all()
    before = cutoff - timedelta(minutes=1)
    assert len(market_state(frame, '1D', before, 'TEST')[1]) == len(chart)-1
    invalid = frame.copy()
    invalid.loc[invalid.index[-1], 'eligible'] = False
    assert len(market_state(invalid, '1D', replay_cutoff(frame.ts.iloc[-1].date()), 'TEST')[1]) == 59
    state, _ = market_state(frame.tail(49), '1D', replay_cutoff(frame.ts.iloc[-1].date()), 'TEST')
    assert state['trend'] == 'UNKNOWN' and '49' in state['reason']


def test_warmup_and_data_integrity_fail_closed():
    frame = sample()
    cutoff = replay_cutoff(frame.ts.iloc[-1].date())
    for config in (BASELINE, Experiment(5,35,20,.1,.05), Experiment(30,50,7,1.5,1.)):
        state, _ = market_state(frame, '1D', cutoff, 'TEST', config)
        assert state['trend'] != 'UNKNOWN'
        assert state['sample_bars'] >= max(config.ema_long, config.atr_period+21)
    for bad in (frame.drop(frame.index[-3]), pd.concat([frame, frame.tail(1)]),
                frame.assign(source=['ONE']*59+['OTHER']).iloc[::-1]):
        assert market_state(bad, '1D', cutoff, 'TEST')[0]['trend'] == 'UNKNOWN'
    bad = frame.copy(); bad.loc[bad.index[-1], 'high'] = 0
    assert market_state(bad, '1D', cutoff, 'TEST')[0]['trend'] == 'UNKNOWN'


def test_snapshot_does_not_mutate_or_consume_later_minutes(market_fixture):
    cutoff = datetime(2026,10,29,16,1,tzinfo=ET)
    original = market_fixture['minute'].copy(deep=True)
    snapshot = completed_snapshot(market_fixture, cutoff)
    assert snapshot['daily'].ts.dt.date.max() < cutoff.date()
    assert (snapshot['minute'].ts + timedelta(minutes=3) <= cutoff).all()
    pd.testing.assert_frame_equal(market_fixture['minute'], original)
    assert snapshot['health']['quality'] == 'UNAVAILABLE'


def test_vendor_daily_and_missing_hour_never_gain_candidate_qualification():
    frame = sample()
    cutoff = replay_cutoff(frame.ts.iloc[-1].date())
    state, _ = market_state(frame, '1D', cutoff, 'VENDOR_DAY')
    data = dict(daily=frame, minute=pd.DataFrame(), daily_only=True)
    assert distance_result(data, state, Experiment(candidate_atr=1.), '1D')['eligible'] is None
    assert distance_result(data, state, BASELINE, '1H')['eligible'] is None


def test_ui_recalculates_restores_and_loads_persisted_parameters(tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setenv('ICT_EXPERIMENT_DB', str(tmp_path/'ui-experiments.sqlite3'))
    script = '''
from datetime import datetime
import pandas as pd
import streamlit as st
from desk.clock import ET, CAL
from desk.decision_home import render_home
wall = datetime(2026,10,29,16,2,tzinfo=ET)
dates = CAL.sessions_in_range('2026-07-01','2026-10-29').tz_localize(None).tz_localize(ET)
values = [100+i*.1+(i%5)*.2 for i in range(len(dates))]
frame = pd.DataFrame(dict(ts=dates,open=values,close=values,volume=10,eligible=True,session='RTH',source='TEST'))
frame['high']=frame.close+1
frame['low']=frame.close-1
data = dict(daily=frame, minute=pd.DataFrame(), health=dict(source='TEST'))
render_home('US.SPY',{'US.SPY':data},None,None,[],[],wall,wall,lambda *args:None)
'''
    app = AppTest.from_string(script, default_timeout=20).run()
    assert not app.exception
    original = app.table[1].value['实验'].tolist()
    app.slider(key='experiment_ema_short').set_value(5).run()
    assert not app.exception
    assert app.table[1].value['实验'].tolist() != original
    app.text_input(key='experiment_name').set_value('界面验收')
    next(b for b in app.button if b.label == '保存组合').click().run()
    assert not app.exception
    next(b for b in app.button if b.label == '恢复默认').click().run()
    assert not app.exception and app.table[1].value['实验'].tolist() == original
    reopened = AppTest.from_string(script, default_timeout=20).run()
    reopened.selectbox(key='experiment_preset').set_value('界面验收').run()
    next(b for b in reopened.button if b.label == '载入组合').click().run()
    assert not reopened.exception
    assert reopened.slider(key='experiment_ema_short').value == 5
    reopened.selectbox(key='experiment_mode').set_value('历史回放').run()
    reopened.selectbox(key='experiment_day').set_value(datetime(2026,10,28).date()).run()
    assert not reopened.exception
    assert any('2026-10-28' in caption.value for caption in reopened.caption)
    reopened.selectbox(key='experiment_period').set_value('1小时').run()
    assert not reopened.exception and any('资料不足' in message.value for message in reopened.info)


def test_legacy_evidence_follows_replay_and_does_not_write_observations(tmp_path, monkeypatch, market_fixture):
    from pathlib import Path
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    from desk.store import Store
    from desk.workspace import historical_ict
    monkeypatch.setenv('ICT_EXPERIMENT_DB', str(tmp_path/'separate-experiments.sqlite3'))
    store = Store(tmp_path/'user-copy.sqlite3')
    with patch('desk.store.Store', return_value=store), patch('desk.provider.Provider.fetch', return_value=market_fixture), \
         patch('desk.workspace.now_et', return_value=datetime(2026,10,30,10,10,tzinfo=ET)), \
         patch('desk.workspace.historical_ict', wraps=historical_ict) as scan, \
         patch.object(store, 'observation', wraps=store.observation) as writes:
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'), default_timeout=30).run()
        assert not app.exception
        app.selectbox(key='experiment_mode').set_value('历史回放').run()
        assert not app.exception
        writes.reset_mock(); scan.reset_mock()
        app.selectbox(key='experiment_day').set_value(datetime(2026,10,28).date()).run()
        assert not app.exception and not writes.called
        assert scan.called
        cutoff = replay_cutoff(datetime(2026,10,28).date())
        for call in scan.call_args_list:
            _, frame, at = call.args
            assert at <= cutoff
            if not frame.empty:
                assert (frame.ts + timedelta(minutes=3) <= cutoff).all()
        assert datetime(2026,10,29).date() in app.selectbox(key='experiment_day').options or '2026-10-29' in app.selectbox(key='experiment_day').options
        writes.reset_mock(); scan.reset_mock()
        app.slider(key='experiment_ema_short').set_value(5).run()
        assert not app.exception
