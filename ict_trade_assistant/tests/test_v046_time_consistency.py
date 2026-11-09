"""Controlled date mismatch tests; the added Nov 9 daily bar is synthetic."""
import copy
import hashlib
import json
import pickle
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from desk.clock import ET
from desk.decision_home import _analysis
from desk.experiment import replay_cutoff
from desk.futu_daily import CONTRACT as DAILY, FUTU
from desk.futu_hourly import CONTRACT as HOURLY, FutuHourlyArchive, verify_hourly
from desk.history_status import period_pair
from test_futu_daily import payload
from test_v046 import hourly_payload

WALL = pd.Timestamp('2026-11-09T16:02:00',tz=ET)


@pytest.fixture
def scenario(hourly_payload):
    hm,hour=verify_hourly(hourly_payload)
    day=pd.DataFrame(hourly_payload['daily_companion']['responses']['QFQ']['records'])
    day['ts']=pd.to_datetime(day.time_key).dt.tz_localize(ET).dt.tz_convert('UTC')
    day['eligible']=True;day['source']=DAILY;day['session']='RTH'
    extra=day.iloc[-1].copy();extra['ts']=pd.Timestamp('2026-11-09',tz=ET).tz_convert('UTC')
    extra['time_key']='2026-11-09 00:00:00'
    for key in ('open','high','low','close'):extra[key]+=1
    updated=pd.concat([day,pd.DataFrame([extra])],ignore_index=True)
    dm=dict(source='FUTU_OPEND',contract=DAILY,adjustment='QFQ',status='PASS',
            valuation_date='2026-11-10',last='2026-11-09',simulation=True,acquired_at=WALL.isoformat())
    hm=dict(hm,valuation_date='2026-11-09',simulation=True)
    return dict(daily=updated,minute=pd.DataFrame(),futu_daily=updated,futu_coverage=dm,
                futu_hourly=hour,hourly_coverage=hm,health=dict(source='SIMULATION',quality='UNAVAILABLE'),
                _price_basis_unverified=True)


def statuses(data,asof=WALL):
    daily,_=_analysis(data['daily'],'1D',asof,DAILY)
    hourly,_=_analysis(data['futu_hourly'],'1H',asof,HOURLY)
    return period_pair(daily,hourly,data['futu_coverage'],data['hourly_coverage'],asof,DAILY,HOURLY)


def app_script(path):
    return f'''
import pickle
import streamlit as st
from desk.decision_home import render_home
from desk.clock import ET
from datetime import datetime
with open({str(path)!r},'rb') as stream: data=pickle.load(stream)
wall=datetime(2026,11,9,16,2,tzinfo=ET)
render_home('US.SPY',data,None,None,[],[],wall,wall,lambda *args:None)
'''


def test_independent_dates_stale_hourly_and_basis_block(scenario):
    pair=statuses(scenario)
    assert pair['daily']['completed_text']=='2026-11-09 16:00 纽约'
    assert pair['hourly']['completed_text']=='2026-11-06 16:00 纽约'
    assert pair['daily']['qualified_history'] and not pair['daily']['stale']
    assert pair['hourly']['description']=='1H历史资料已过期'
    assert not pair['hourly']['qualified_history']
    assert pair['daily']['valuation_date']=='2026-11-10' and pair['hourly']['valuation_date']=='2026-11-09'
    assert pair['cross_scale_blocked'] and '价格尺度未获统一认证' in pair['scale_notice']
    assert pair['executable_risk_reward'] is None and not pair['trading_eligible']


def test_replay_uses_selected_time_and_quarantine(scenario):
    pair=statuses(scenario,replay_cutoff(pd.Timestamp('2026-11-06').date()))
    assert pair['daily']['completed_text']==pair['hourly']['completed_text']=='2026-11-06 16:00 纽约'
    assert pair['hourly']['qualified_history'] and not pair['hourly']['stale']
    early=statuses(scenario,pd.Timestamp('2026-11-09T16:01:59',tz=ET))
    assert early['daily']['completed_text']=='2026-11-06 16:00 纽约'


def test_daily_refresh_preserves_hourly_bytes_values_and_qualification(tmp_path,scenario,hourly_payload):
    blob=json.dumps(hourly_payload).encode();(tmp_path/'SPY.json').write_bytes(blob)
    (tmp_path/'manifest.json').write_text(json.dumps(dict(symbols={'US.SPY':dict(status='PASS',sha256=hashlib.sha256(blob).hexdigest())})))
    archive=FutuHourlyArchive(tmp_path);before=archive.read('US.SPY')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    original=copy.deepcopy(scenario)
    original['daily']=original['daily'].iloc[:-1].copy()
    old=statuses(original);new=statuses(scenario)
    after=archive.read('US.SPY')
    assert before[0]==after[0] and before[0]['status']=='PASS'
    pd.testing.assert_frame_equal(before[1],after[1])
    assert old['hourly']==new['hourly']
    assert hashes=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}


@pytest.mark.parametrize('code,reason',[
    ('US.VEA','US.VEA/2026-11-06/QFQ：60分钟汇总与同批日K不一致'),
    ('US.IEFA','US.IEFA/2026-11-03/QFQ：60分钟汇总与同批日K不一致'),
    ('US.BND','US.BND/2026-09-30/QFQ：60分钟汇总与同批日K不一致')])
def test_rejected_hourly_reason_is_not_overwritten_by_daily_freshness(scenario,code,reason):
    scenario['futu_hourly']=pd.DataFrame()
    scenario['hourly_coverage']=dict(status='UNAVAILABLE',reason=reason,ict_eligible=False)
    pair=statuses(scenario)
    assert pair['hourly']['status']=='REJECTED' and pair['hourly']['reason']==reason
    assert pair['hourly']['completed_text']=='无已验收资料' and pair['hourly']['valuation_date']=='未提供'
    assert not pair['hourly']['qualified_history'] and pair['daily']['qualified_history']


def test_fifteen_cards_and_main_summary_show_both_periods(tmp_path,scenario,monkeypatch):
    monkeypatch.setenv('ICT_EXPERIMENT_DB',str(tmp_path/'experiment.sqlite3'))
    codes=['US.SPY','US.QQQ','US.IWM','US.SOXX','US.SMH','US.VOO','US.IVV','US.VTI',
           'US.VUG','US.VTV','US.SPYM','US.VXUS','US.IEMG','US.VGT','US.GLD']
    data={code:copy.deepcopy(scenario) for code in codes}
    path=tmp_path/'controlled-scenario.pickle';path.write_bytes(pickle.dumps(data))
    with patch('desk.decision_home.manual_prices',side_effect=AssertionError('cross-scale risk/reward forbidden')):
        app=AppTest.from_string(app_script(path),default_timeout=45).run()
    assert not app.exception
    cards=[m.value for m in app.markdown if '<article class="dash-candidate"' in m.value]
    main=next(m.value for m in app.markdown if '<section class="dash-summary"' in m.value)
    assert len(cards)==15
    for html in cards+[main]:
        assert '日K最后完成：2026-11-09 16:00 纽约' in html
        assert '1H最后完成：2026-11-06 16:00 纽约' in html
        assert DAILY in html and HOURLY in html and '2026-11-10' in html and '2026-11-09' in html
        assert '1H历史资料已过期' in html and '1H合格' not in html
        assert '价格尺度未获统一认证' in html
    app.selectbox(key='experiment_period').set_value('1小时').run()
    assert not app.exception and any('数据太旧不能判断' in m.value for m in app.markdown if '<section class="dash-summary"' in m.value)
    assert not app.checkbox
    app.selectbox(key='experiment_mode').set_value('历史回放').run()
    app.selectbox(key='experiment_day').set_value(pd.Timestamp('2026-11-06').date()).run()
    assert not app.exception
    replay=next(m.value for m in app.markdown if '<section class="dash-summary"' in m.value)
    assert '1H历史资料已过期' not in replay and '1H合格（仅历史）' in replay


def test_hourly_newer_than_daily_is_not_truncated_to_daily_cutoff(tmp_path,scenario,monkeypatch):
    monkeypatch.setenv('ICT_EXPERIMENT_DB',str(tmp_path/'experiment.sqlite3'))
    data=copy.deepcopy(scenario)
    data['daily']=data['daily'].iloc[:-1].copy();data['futu_daily']=data['daily']
    data['futu_coverage']=dict(data['futu_coverage'],last='2026-11-06')
    last=data['futu_hourly'].iloc[-1].copy()
    last['ts']=pd.Timestamp('2026-11-09T09:30:00',tz=ET).tz_convert('UTC')
    last['end_at']=last['ts']+pd.Timedelta(hours=1);last['duration_minutes']=60
    data['futu_hourly']=pd.concat([data['futu_hourly'],pd.DataFrame([last])],ignore_index=True)
    path=tmp_path/'controlled-scenario.pickle';path.write_bytes(pickle.dumps({'US.SPY':data}))
    app=AppTest.from_string(app_script(path),default_timeout=45).run()
    assert not app.exception
    main=next(m.value for m in app.markdown if '<section class="dash-summary"' in m.value)
    assert '日K最后完成：2026-11-06' in main and '1H最后完成：2026-11-09 10:30' in main
