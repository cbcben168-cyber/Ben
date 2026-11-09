from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
import sqlite3

import pandas as pd
import plotly.graph_objects as go
import pytest
from streamlit.testing.v1 import AppTest

from desk.clock import ET
from desk.ema_layers import ema_points, add_ema_lines, UNAVAILABLE
from desk.experiment import BASELINE, ExperimentStore, replay_cutoff
from desk.market_state import market_state
from test_experiment_v044 import sample


@pytest.mark.parametrize('config', [BASELINE, replace(BASELINE, ema_short=5, ema_long=35)])
def test_every_ema_point_matches_qualified_rolling_sample_and_table(config):
    frame = sample()
    cutoff = replay_cutoff(frame.ts.iloc[-1].date())
    points = ema_points(frame, '1D', cutoff, 'TEST', config)
    assert len(points) == 11  # First 49 candles intentionally have no line.
    for point in points.itertuples():
        point_cutoff = replay_cutoff(point.ts.date())
        state, _ = market_state(frame, '1D', point_cutoff, 'TEST', config)
        assert point.short == state['ema20'] and point.long == state['ema50']
        assert point.ts <= cutoff
    state, _ = market_state(frame, '1D', cutoff, 'TEST', config)
    assert points.short.iloc[-1] == state['ema20']
    assert points.long.iloc[-1] == state['ema50']
    assert points.short.iloc[-1] != frame.close.ewm(span=config.ema_short, adjust=False).mean().iloc[-1]


def test_no_future_prices_or_unqualified_indicator_lines():
    frame = sample()
    cutoff = replay_cutoff(frame.ts.iloc[-2].date())
    poisoned = frame.copy()
    poisoned.loc[poisoned.ts > cutoff, ['open','high','low','close']] = 999999.
    pd.testing.assert_frame_equal(ema_points(frame,'1D',cutoff,'TEST'), ema_points(poisoned,'1D',cutoff,'TEST'))
    assert ema_points(frame.tail(49),'1D',cutoff,'TEST').empty
    assert ema_points(frame,'1D',cutoff,'UNKNOWN').empty
    assert ema_points(frame.drop(frame.index[-3]),'1D',cutoff,'TEST').empty
    assert ema_points(pd.DataFrame(),'1H',cutoff,'TEST').empty


def test_layer_names_styles_and_restore_overlap():
    frame=sample();cutoff=replay_cutoff(frame.ts.iloc[-1].date())
    original=ema_points(frame,'1D',cutoff,'TEST')
    config=replace(BASELINE,ema_short=5)
    experiment=ema_points(frame,'1D',cutoff,'TEST',config)
    fig=go.Figure()
    add_ema_lines(fig,original,BASELINE,True);add_ema_lines(fig,experiment,config)
    assert [trace.name for trace in fig.data]==['原始EMA20','原始EMA50','实验EMA5','实验EMA50']
    assert [trace.line.dash for trace in fig.data]==['dash','dash','solid','solid']
    assert fig.data[0].opacity<fig.data[2].opacity
    assert fig.data[2].line.color!=fig.data[3].line.color
    assert list(fig.data[0].y)!=list(fig.data[2].y)
    restored=go.Figure();add_ema_lines(restored,original,BASELINE,True);add_ema_lines(restored,original,BASELINE)
    assert list(restored.data[0].y)==list(restored.data[2].y)
    assert list(restored.data[1].y)==list(restored.data[3].y)


def test_exactly_fifty_candles_show_one_qualified_endpoint():
    frame=sample().tail(50)
    points=ema_points(frame,'1D',replay_cutoff(frame.ts.iloc[-1].date()),'TEST')
    assert len(points)==1
    fig=go.Figure();add_ema_lines(fig,points,BASELINE)
    assert all(t.mode=='lines+markers' for t in fig.data)


def test_old_profiles_remain_loadable_without_rewriting_them(tmp_path):
    path=tmp_path/'profiles.sqlite3';store=ExperimentStore(path)
    config=replace(BASELINE,ema_short=5)
    store.save('旧版本实验',config)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE experiments SET version='v0.4.4' WHERE name='旧版本实验'")
        before=db.execute('SELECT * FROM experiments').fetchall()
    assert store.load_profile('旧版本实验')==dict(config=config,version='v0.4.4')
    assert store.load('旧版本实验')==config
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT * FROM experiments').fetchall()==before
    store.save('新版本实验',config)
    assert store.load_profile('新版本实验')['version']=='v0.4.4.1'
    with pytest.raises(ValueError):store.save('Baseline',config)


SCRIPT = '''
from datetime import datetime
import pandas as pd
import streamlit as st
from desk.clock import ET, CAL
from desk.decision_home import render_home
wall=datetime(2026,10,29,16,2,tzinfo=ET)
dates=CAL.sessions_in_range('2026-07-01','2026-10-29').tz_localize(None).tz_localize(ET)
values=[100+i*.1+(i%5)*.2 for i in range(len(dates))]
frame=pd.DataFrame(dict(ts=dates,open=values,close=values,volume=10,eligible=True,session='RTH',source='TEST'))
frame['high']=frame.close+1;frame['low']=frame.close-1
data={code:dict(daily=frame.copy(),minute=pd.DataFrame(),health=dict(source='TEST')) for code in ['US.SPY','US.QQQ','US.SMH']}
st.selectbox('证券',list(data),key='test_symbol')
plan=dict(symbol='US.SPY',status='ACTIVE',strategy_version='test',memo='',direction='LONG',low=100,high=101,invalid=95,target_low=110,target_high=120,version=1,updated_at='2026-10-01T00:00:00Z')
render_home(st.session_state.test_symbol,data,plan,None,[],[],wall,wall,lambda *args:None)
'''


def button(app,label):return next(b for b in app.button if b.label==label)
def status(app):return next(m.value for m in app.markdown if 'factor-active' in m.value)
def ema_traces(app):
    spec=json.loads(app.get('plotly_chart')[0].proto.spec)
    return [t for t in spec['data'] if t.get('meta',{}).get('kind')=='historical_ema']
def values(app):return {key:app.slider(key='experiment_'+key).value for key in asdict(BASELINE)}


def test_effective_profile_is_not_the_dropdown_and_survives_symbol_date_changes(tmp_path,monkeypatch):
    path=tmp_path/'ui.sqlite3';monkeypatch.setenv('ICT_EXPERIMENT_DB',str(path))
    store=ExperimentStore(path);store.save('准备实验',replace(BASELINE,ema_short=10))
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    assert not app.exception and 'Baseline（原始参数）' in status(app)
    app.selectbox(key='experiment_preset').set_value('准备实验').run()
    assert 'Baseline（原始参数）' in status(app) and values(app)==asdict(BASELINE)
    button(app,'载入组合').click().run()
    assert '准备实验（已修改）' in status(app) and values(app)['ema_short']==10
    app.slider(key='experiment_ema_short').set_value(5).run()
    assert '自定义参数（未保存）' in status(app)
    app.text_input(key='experiment_name').set_value('EMA快速实验')
    button(app,'保存组合').click().run()
    assert 'EMA快速实验（已修改）' in status(app)
    assert any('保存成功：EMA快速实验（版本 v0.4.4.1）' in m.value for m in app.success)
    saved=values(app)
    app.slider(key='experiment_atr_period').set_value(7).run()
    assert '自定义参数（未保存）' in status(app)
    app.selectbox(key='experiment_preset').set_value('准备实验').run()
    assert values(app)['atr_period']==7 and '自定义参数（未保存）' in status(app)
    app.selectbox(key='experiment_preset').set_value('EMA快速实验').run()
    button(app,'载入组合').click().run()
    assert values(app)==saved and 'EMA快速实验（已修改）' in status(app)
    app.selectbox(key='test_symbol').set_value('US.QQQ').run()
    app.selectbox(key='experiment_mode').set_value('历史回放').run()
    app.selectbox(key='experiment_day').set_value(datetime(2026,10,28).date()).run()
    assert not app.exception and values(app)==saved and 'EMA快速实验（已修改）' in status(app)
    button(app,'恢复默认').click().run()
    assert values(app)==asdict(BASELINE) and 'Baseline（原始参数）' in status(app)
    assert app.selectbox(key='experiment_preset').value=='Baseline'
    reopened=AppTest.from_string(SCRIPT,default_timeout=30).run()
    reopened.selectbox(key='experiment_preset').set_value('EMA快速实验').run()
    button(reopened,'载入组合').click().run()
    assert not reopened.exception and values(reopened)==saved and 'EMA快速实验（已修改）' in status(reopened)


def test_chart_modes_match_table_and_manual_layers_remain_independent(tmp_path,monkeypatch):
    monkeypatch.setenv('ICT_EXPERIMENT_DB',str(tmp_path/'ui.sqlite3'))
    app=AppTest.from_string(SCRIPT,default_timeout=30).run()
    assert not app.exception
    assert [t['name'] for t in ema_traces(app)]==['实验EMA20','实验EMA50']
    for trace,label in zip(ema_traces(app),['短期EMA','长期EMA']):
        row=app.table[1].value.set_index('数值').loc[label]
        assert abs(trace['y'][-1]-float(row['实验']))<.000001
    app.selectbox(key='ema_layer_mode').set_value('对比原始EMA与实验EMA').run()
    app.slider(key='experiment_ema_short').set_value(5).run()
    traces=ema_traces(app)
    assert [t['name'] for t in traces]==['原始EMA20','原始EMA50','实验EMA5','实验EMA50']
    assert traces[0]['y']!=traces[2]['y']
    assert abs(traces[2]['y'][-1]-float(app.table[1].value.set_index('数值').loc['短期EMA','实验']))<.000001
    button(app,'恢复默认').click().run()
    traces=ema_traces(app)
    assert traces[0]['y']==traces[2]['y'] and traces[1]['y']==traces[3]['y']
    app.checkbox[0].set_value(True).run()
    spec=json.loads(app.get('plotly_chart')[0].proto.spec)
    assert any(t.get('name','').startswith('人工计划') for t in spec['data'])
    app.selectbox(key='ema_layer_mode').set_value('不显示指标').run()
    assert not app.exception and not ema_traces(app)
    spec=json.loads(app.get('plotly_chart')[0].proto.spec)
    assert any(t.get('name','').startswith('人工计划') for t in spec['data'])
    assert any('重点观察的15只证券（自选显示顺序）' in h.value for h in app.subheader)
    assert not any('Top5' in h.value for h in app.subheader)


def test_insufficient_data_shows_explanation_instead_of_ema(tmp_path,monkeypatch):
    monkeypatch.setenv('ICT_EXPERIMENT_DB',str(tmp_path/'ui.sqlite3'))
    app=AppTest.from_string(SCRIPT.replace("frame['high']=", "frame=frame.tail(49).copy()\nframe['high']="),default_timeout=30).run()
    assert not app.exception and not ema_traces(app)
    assert any(UNAVAILABLE in message.value for message in app.info)
