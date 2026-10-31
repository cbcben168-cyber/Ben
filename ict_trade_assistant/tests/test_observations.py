from copy import deepcopy
from datetime import datetime, timedelta, date
import pandas as pd
import pytest
from desk.clock import ET
from desk.store import Store, DEFAULTS
from desk.observations import build_observation, ranked, record_events, context, live_health, parameter_version
from desk.event_contract import ICTEvent


def dt(value): return datetime.fromisoformat(value).replace(tzinfo=ET)


def test_closed_historical_candidates_and_no_market_alerts(market_fixture,tmp_path):
    now=dt('2026-10-30T08:00')
    data=deepcopy(market_fixture);data['health']['quality']='STALE'
    o=build_observation('US.SPY',data,DEFAULTS,now,dict(low=99,high=101,direction='LONG'))
    assert o['mode']=='PREPARATION' and o['status']=='AVAILABLE'
    assert o['reference_price']==100 and o['reference_day']=='2026-10-29'
    assert o['candidates'] and all('非实时' in r['distance_basis'] for r in o['candidates'])
    assert o['levels']['PREVIOUS_RTH']['high']==102
    store=Store(tmp_path/'events.db')
    for _ in range(3):
        store.observation(o);record_events(store,o)
    assert store.table('market_events').empty
    assert len(store.table('system_events'))==1
    assert len(store.table('observations'))==1


def test_live_then_stale_retains_history(market_fixture):
    now=dt('2026-10-30T10:10')
    live=build_observation('US.SPY',market_fixture,DEFAULTS,now)
    stale=build_observation('US.SPY',market_fixture,DEFAULTS,now+timedelta(seconds=91))
    assert live['mode']=='LIVE' and live['reference_at']==now.isoformat()
    assert stale['mode']=='HISTORICAL_ONLY' and stale['status']=='AVAILABLE'
    assert stale['health']['quality']=='STALE' and stale['reference_price']==100
    assert all(r['mode']=='HISTORICAL_ONLY' for r in stale['candidates'])


@pytest.mark.parametrize('damage',['minute','daily','missing_minute','duplicate_day','missing_day'])
def test_incomplete_returns_unavailable(market_fixture,damage):
    data=deepcopy(market_fixture)
    if damage in ('minute','daily'): data[damage]=pd.DataFrame()
    elif damage=='missing_minute': data['minute']=data['minute'].iloc[1:]
    elif damage=='duplicate_day': data['daily']=pd.concat([data['daily'],data['daily'].tail(1)])
    else: data['daily']=data['daily'].iloc[:-1]
    o=build_observation('US.SPY',data,DEFAULTS,dt('2026-10-30T08:00'))
    assert o['status']=='UNAVAILABLE' and not o['candidates']


@pytest.mark.parametrize('stamp,target,ref',[
    ('2026-10-30T17:00','2026-11-02','2026-10-30'),
    ('2026-11-01T12:00','2026-11-02','2026-10-30'),
    ('2026-11-02T08:00','2026-11-02','2026-10-30'),
    ('2026-11-26T12:00','2026-11-27','2026-11-25'),
    ('2026-11-27T13:01','2026-11-30','2026-11-27')])
def test_calendar_context(stamp,target,ref):
    result=context(dt(stamp))
    assert result['mode']=='PREPARATION' and result['trading_day']==target and result['reference_day']==ref


def test_live_rejects_future_permission_cross_session(market_fixture):
    h=market_fixture['health'];now=dt('2026-10-30T10:10')
    assert live_health(h,now)['quality']=='AVAILABLE'
    assert live_health(dict(h,right='UNKNOWN'),now)['quality']=='UNAVAILABLE'
    assert live_health(dict(h,quote_at=(now+timedelta(seconds=6)).isoformat()),now)['quality']=='UNAVAILABLE'
    assert live_health(h,dt('2026-10-30T18:00'))['quality']!='AVAILABLE'


def test_candidate_sort_zero_and_parameter_versions(market_fixture):
    now=dt('2026-10-30T08:00')
    zone=dict(low=99.,high=101.,direction='LONG')
    obs={s:build_observation(s,market_fixture,DEFAULTS,now,zone) for s in ('US.SPY','US.QQQ','US.VIX')}
    rows=ranked(obs)
    assert rows[0]['key']=='MANUAL' and rows[1]['key']=='MANUAL'
    assert all(r['symbol']!='US.VIX' for r in rows)
    empty=build_observation('US.SPY',market_fixture,dict(DEFAULTS,candidate_atr=.01),now)
    assert empty['status']=='AVAILABLE' and not empty['candidates']
    assert parameter_version(DEFAULTS)!=parameter_version(dict(DEFAULTS,candidate_atr=.3))
    assert rows[0]['parameter_version']!=build_observation('US.QQQ',market_fixture,DEFAULTS,now,dict(zone,high=103))['parameter_version']


def test_transition_dedupe_reentry_out_of_order_and_channels(tmp_path):
    store=Store(tmp_path/'events.db')
    for state,second in [('NEAR',0),('NEAR',0),('NEAR',1),('OUTSIDE',2),('NEAR',3),('OUTSIDE',1)]:
        store.transition('MARKET','US.SPY','PDH',state,(dt('2026-10-30T10:00')+timedelta(seconds=second)).isoformat(),state,{},'scope')
    assert store.table('market_events').reason.tolist()==['NEAR','OUTSIDE','NEAR']
    for i in range(310):
        store.event('SYSTEM_HEALTH','US.SPY','system')
    assert len(store.table('market_events'))==3 and len(store.table('system_events'))==300


def test_real_event_changes_only_and_stale_no_alert(market_fixture,tmp_path):
    store=Store(tmp_path/'events.db'); now=dt('2026-10-30T10:10')
    o=build_observation('US.SPY',market_fixture,DEFAULTS,now,dict(low=99,high=101,direction='LONG'))
    record_events(store,o);record_events(store,o)
    initial=len(store.table('market_events')); assert initial>0
    record_events(store,build_observation('US.SPY',market_fixture,DEFAULTS,now+timedelta(seconds=91)))
    assert len(store.table('market_events'))==initial


def test_contract_blocks_unfinished_confirmation():
    values=dict(kind='MSS',symbol='US.SPY',timeframe='15m',direction='LONG',key_price=100.,
                occurred_at=dt('2026-10-30T10:00'),confirmed_at=dt('2026-10-30T10:15'),
                bar_end=dt('2026-10-30T10:15'),source='TEST',parameter_version='v1',
                status='CONFIRMED',invalidation='跌破人工失效价')
    with pytest.raises(ValueError): ICTEvent(**values)
    assert ICTEvent(**values,completed_bar=True).payload()['status']=='CONFIRMED'
    with pytest.raises(ValueError): ICTEvent(**dict(values,confirmed_at=dt('2026-10-30T10:14')),completed_bar=True)


def test_native_close_not_last_minute_and_ohlc_crosscheck(market_fixture):
    data=deepcopy(market_fixture)
    data['daily'].loc[data['daily'].ts.dt.date==date(2026,10,29),'close']=100.5
    o=build_observation('US.SPY',data,DEFAULTS,dt('2026-10-30T08:00'))
    assert o['reference_price']==100.5 and o['close_verification']['last_minute_close']==100
    data['daily'].loc[data['daily'].ts.dt.date==date(2026,10,29),'high']=103
    assert build_observation('US.SPY',data,DEFAULTS,dt('2026-10-30T08:00'))['status']=='UNAVAILABLE'


def test_daily_early_close_completion_quarantine():
    from desk.analytics import normalize
    raw=pd.DataFrame([dict(time_key='2026-11-27 00:00:00',open=100,high=102,low=98,close=101,volume=1)])
    assert not normalize(raw,'DAY',dt('2026-11-27T13:01')).iloc[0].eligible
    assert normalize(raw,'DAY',dt('2026-11-27T13:02')).iloc[0].eligible


def test_parameter_version_is_audited(tmp_path):
    store=Store(tmp_path/'parameters.db')
    before=parameter_version(store.settings())
    store.save('candidate_atr',.4)
    import json
    audit=store.table('audit')
    row=audit[audit.key=='observation_parameter_version'].iloc[0]
    assert json.loads(row.old)==before and json.loads(row.new)==parameter_version(store.settings())


def test_candidate_ui_preserves_saved_note_plan_and_focus(market_fixture,tmp_path):
    from unittest.mock import patch
    from pathlib import Path
    import json
    from streamlit.testing.v1 import AppTest
    store=Store(tmp_path/'notes.db')
    store.note('US.QQQ','候选切换前已保存备注')
    p=dict(symbol='US.QQQ',strategy_version='manual-test',direction='LONG',low=99,high=101,
           invalid=98,target_low=105,target_high=106,memo='保留原计划')
    ident,_=store.save_plan(p)
    with patch('desk.store.Store',return_value=store),patch('desk.provider.Provider.fetch',return_value=market_fixture),patch('desk.workspace.now_et',return_value=dt('2026-10-30T10:10')):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
        app.button(key='pick_US.QQQ_MANUAL').click().run()
        assert app.session_state['desk_symbol']=='US.QQQ'
        assert app.session_state['desk_candidate']==('US.QQQ','MANUAL')
        assert any('候选切换前已保存备注' in x.value for x in app.markdown)
        plot=json.loads(app.get('plotly_chart')[0].proto.spec)
        assert any(a.get('text')=='当前关注 MANUAL' for a in plot['layout']['annotations'])
        next(r for r in app.radio if r.label=='周期').set_value('4H').run()
        assert not app.exception and app.session_state['desk_candidate']==('US.QQQ','MANUAL')
    assert store.note('US.QQQ')=='候选切换前已保存备注'
    assert len(store.plan_history(ident))==1 and store.plans('US.QQQ')[0]['memo']=='保留原计划'
