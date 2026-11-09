import copy
from datetime import timedelta
import hashlib
import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from desk.clock import bounds, ET
from desk.experiment import replay_cutoff
from desk.futu_daily import attach_futu, FutuDailyArchive, CONTRACT as DAILY
from desk.futu_hourly import (CONTRACT, FutuHourlyArchive, verify_hourly, session_grid,
                              hourly_prefix, attach_hourly)
from desk.historical_prices import references, target_readiness, focus_symbols, nearest_reference
from desk.market_state import market_state
from desk.ema_layers import ema_points
from test_futu_daily import payload


@pytest.fixture
def hourly_payload(payload):
    responses = {}
    for adj in ('QFQ', 'NONE'):
        response = copy.deepcopy(payload['responses'][adj])
        response['request']['ktype'] = 'K_60M'
        grid = session_grid(response['request']['start'], response['request']['end'])
        by_day = {r['time_key'][:10]:r for r in response['records']}
        records = []
        for start, end in grid:
            row = copy.deepcopy(by_day[start.tz_convert(ET).date().isoformat()])
            row['time_key'] = end.tz_convert(ET).strftime('%Y-%m-%d %H:%M:%S')
            row['volume'] /= 7
            records.append(row)
        response['records'] = records
        responses[adj] = response
    return dict(format='FUTU_HOURLY_V1', symbol=payload['symbol'], valuation_date=payload['valuation_date'],
                daily_companion=payload, responses=responses)


def test_native_end_labels_utc_duration_and_frozen_indicators(hourly_payload):
    meta, frame = verify_hourly(hourly_payload)
    assert meta['bars'] == 630 and not meta['ict_eligible']
    assert str(frame.ts.dt.tz) == 'UTC'
    assert frame.ts.iloc[0].tz_convert(ET).strftime('%H:%M') == '09:30'
    assert frame.end_at.iloc[0].tz_convert(ET).strftime('%H:%M') == '10:30'
    assert frame.duration_minutes.iloc[6] == 30
    assert frame.end_at.iloc[6].tz_convert(ET).strftime('%H:%M') == '16:00'
    assert frame.ts.iloc[0].hour == 13 and frame.ts.iloc[-7].hour == 14  # DST fall-back.
    asof = replay_cutoff(pd.Timestamp('2026-11-06').date())
    state, chart = market_state(frame,'1H',asof,CONTRACT)
    assert state['trend'] != 'UNKNOWN' and state['sample_bars'] == 50
    sample = chart.tail(50)
    assert state['ema20'] == sample.close.ewm(span=20,adjust=False,min_periods=20).mean().iloc[-1]
    assert state['ema50'] == sample.close.ewm(span=50,adjust=False,min_periods=50).mean().iloc[-1]
    tr = pd.concat([sample.high-sample.low,(sample.high-sample.close.shift()).abs(),
                    (sample.low-sample.close.shift()).abs()],axis=1).max(axis=1)
    assert state['atr14'] == tr.tail(14).mean()
    points = ema_points(chart,'1H',asof,CONTRACT)
    assert points.short.iloc[-1] == state['ema20']


def test_early_close_grid_and_confirmation_quarantine(hourly_payload):
    grid = session_grid('2025-11-28','2025-11-28')
    assert len(grid) == 4
    assert [(a.tz_convert(ET).strftime('%H:%M'),b.tz_convert(ET).strftime('%H:%M')) for a,b in grid] == [
        ('09:30','10:30'),('10:30','11:30'),('11:30','12:30'),('12:30','13:00')]
    _, frame = verify_hourly(hourly_payload)
    end = frame.end_at.iloc[59]
    prefix = hourly_prefix(frame,end+timedelta(minutes=2)-timedelta(microseconds=1))
    assert len(prefix) == 59
    assert len(hourly_prefix(frame,end+timedelta(minutes=2))) == 60
    state, chart = market_state(frame,'1H',end+timedelta(minutes=2),CONTRACT)
    changed = frame.copy(); changed.loc[changed.ts>frame.ts.iloc[59],['open','high','low','close']]*=10
    other, _ = market_state(changed,'1H',end+timedelta(minutes=2),CONTRACT)
    assert other == state
    assert (chart.end_at+pd.Timedelta(minutes=2)<=end+timedelta(minutes=2)).all()


@pytest.mark.parametrize('mutation', ['missing','duplicate','start_labels','session','qfq','future','ohlc'])
def test_invalid_hourly_is_rejected(hourly_payload, mutation):
    p=copy.deepcopy(hourly_payload); response=p['responses']['QFQ']
    if mutation=='missing': response['records'].pop(20)
    if mutation=='duplicate': response['records'][20]=response['records'][19]
    if mutation=='start_labels': response['records'][0]['time_key']='2026-07-02 09:30:00'
    if mutation=='session': response['request']['session']='ALL'
    if mutation=='qfq': p['valuation_date']='2020-01-01'
    if mutation=='future': response['acquired_at_utc']='2099-01-01T00:00:00Z'
    if mutation=='ohlc': response['records'][20]['high']=0
    with pytest.raises(ValueError): verify_hourly(p)


def test_hourly_archive_hash_readonly_and_never_attaches_to_minute(tmp_path,hourly_payload):
    blob=json.dumps(hourly_payload).encode(); (tmp_path/'SPY.json').write_bytes(blob)
    manifest=dict(symbols={'US.SPY':dict(status='PASS',sha256=hashlib.sha256(blob).hexdigest())})
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    original_minute=pd.DataFrame([dict(test='original minute evidence')])
    original=dict(minute=original_minute,daily=pd.DataFrame())
    result=attach_hourly(original,tmp_path,'US.SPY')
    assert result['minute'] is original_minute and 'futu_hourly' in result
    assert result['hourly_coverage']['ict_eligible'] is False
    assert (tmp_path/'SPY.json').read_bytes()==blob
    (tmp_path/'SPY.json').write_bytes(blob+b' ')
    failed=attach_hourly(original,tmp_path,'US.SPY')
    assert failed['futu_hourly'].empty and 'SHA256' in failed['hourly_coverage']['reason']
    assert failed['minute'] is original_minute


def test_references_have_actual_day_week_twenty_day_prices_and_no_ict_dependency(tmp_path,payload):
    archive=FutuDailyArchive.create(tmp_path/'daily.sqlite3'); archive.import_payload(payload)
    meta,frame=archive.read('US.SPY'); asof=replay_cutoff(pd.Timestamp('2026-11-06').date())
    refs=references(frame,asof,DAILY,meta)
    assert [r['name'] for r in refs['levels']]==['前交易日','前一完整交易周','最近20个已完成交易日']
    by_date={r['time_key'][:10]:r for r in payload['responses']['QFQ']['records']}
    assert refs['levels'][0]['high']==by_date['2026-11-05']['high']
    assert refs['levels'][0]['low']==by_date['2026-11-05']['low']
    week=refs['levels'][1]
    assert (week['from_date'],week['to_date'])==('2026-10-26','2026-10-30')
    assert week['high']==max(by_date[d]['high'] for d in by_date if '2026-10-26'<=d<='2026-10-30')
    assert refs['levels'][2]['high']==frame.tail(20).high.max()
    assert refs['levels'][2]['from_date']==frame.tail(20).ts.iloc[0].date().isoformat()
    assert all(r['capture_sha256']==meta['capture_sha256'] and r['source']==DAILY for r in refs['levels'])
    assert refs['missing']==['1H结构参考位：尚无已验收1小时历史资料']
    altered=frame.copy();altered.loc[altered.ts>pd.Timestamp('2026-10-28',tz=ET),'high']*=10
    cutoff=replay_cutoff(pd.Timestamp('2026-10-28').date())
    assert references(frame,cutoff,DAILY,meta)==references(altered,cutoff,DAILY,meta)
    latest=references(frame,pd.Timestamp('2026-11-09T03:00:00',tz=ET),DAILY,meta)
    assert latest['levels'][0]['from_date']=='2026-11-06'
    assert (latest['levels'][1]['from_date'],latest['levels'][1]['to_date'])==('2026-11-02','2026-11-06')


def test_confirmed_hourly_pivot_waits_for_two_right_bars_and_never_mixes_basis(tmp_path,payload,hourly_payload):
    archive=FutuDailyArchive.create(tmp_path/'daily.sqlite3');archive.import_payload(payload)
    daily_meta,daily=archive.read('US.SPY'); meta,hourly=verify_hourly(hourly_payload)
    hourly.loc[hourly.index[-5],'high'] += 20
    asof=hourly.end_at.iloc[-4]+pd.Timedelta(minutes=2)
    before=references(daily,asof,DAILY,daily_meta,hourly,meta)
    assert not any(r['name']=='已确认1H摆动高点' and r['high']==hourly.high.iloc[-5] for r in before['levels'])
    asof=hourly.end_at.iloc[-3]+pd.Timedelta(minutes=2)
    after=references(daily,asof,DAILY,daily_meta,hourly,meta)
    assert any(r['name']=='已确认1H摆动高点' and r['high']==hourly.high.iloc[-5] for r in after['levels'])
    wrong=references(daily,asof,DAILY,daily_meta,hourly,dict(meta,valuation_date='2020-01-01'))
    assert not any(r['name'].startswith('已确认1H') for r in wrong['levels'])
    assert any('估值日不同' in m for m in wrong['missing'])


def test_focus_fifteen_is_session_only_and_preserves_enabled_order():
    enabled=['US.'+chr(65+i) for i in range(23)]
    original=list(enabled)
    assert focus_symbols(enabled)==enabled[:15]
    assert focus_symbols(enabled,[enabled[20],enabled[2],enabled[0],'US.DISABLED',enabled[2]])==[enabled[20],enabled[2],enabled[0]]
    assert focus_symbols(enabled[:2])==enabled[:2] and focus_symbols(enabled,[])==[]
    assert focus_symbols(['US.VIX']+enabled)==enabled[:15] and enabled==original
    assert nearest_reference(dict(close=100,levels=[dict(name='参考',low=99.1234567,high=100.1234567)])) == '参考 99.1234567–100.1234567'


def test_focus_ui_fifteen_reorders_selects_and_reopens_without_persistence(tmp_path,monkeypatch):
    from test_v0441 import SCRIPT
    monkeypatch.setenv('ICT_EXPERIMENT_DB',str(tmp_path/'experiment.sqlite3'))
    codes=['US.SPY','US.QQQ','US.IWM','US.SOXX','US.SMH','US.VOO','US.IVV','US.VTI',
           'US.VEA','US.VUG','US.IEFA','US.VTV','US.SPYM','US.BND','US.VXUS','US.XLK']
    script=SCRIPT.replace("['US.SPY','US.QQQ','US.SMH']",repr(codes))
    script=script.replace('render_home(st.session_state.test_symbol',
        'def select(code,key):\n    st.session_state.test_symbol=code\nrender_home(st.session_state.test_symbol')
    script=script.replace('lambda *args:None','select')
    app=AppTest.from_string(script,default_timeout=30).run()
    assert not app.exception and app.multiselect(key='focus_symbols').value==codes[:15]
    assert len([m for m in app.markdown if '<article class="dash-candidate"' in m.value])==15
    app.multiselect(key='focus_symbols').set_value(['US.XLK','US.SMH']).run()
    cards=[m.value for m in app.markdown if '<article class="dash-candidate"' in m.value]
    assert len(cards)==2 and 'XLK 历史观察卡' in cards[0] and 'SMH 历史观察卡' in cards[1]
    app.button(key='watch_US.SMH').click().run()
    assert not app.exception and app.selectbox(key='test_symbol').value=='US.SMH'
    assert any('SMH｜价格观察与行动' in m.value for m in app.markdown)
    reopened=AppTest.from_string(script,default_timeout=30).run()
    assert reopened.multiselect(key='focus_symbols').value==codes[:15]


def test_manual_raw_values_visible_unverified_scale_and_qualification_stays_closed(tmp_path,monkeypatch):
    from test_v0441 import SCRIPT
    monkeypatch.setenv('ICT_EXPERIMENT_DB',str(tmp_path/'experiment.sqlite3'))
    script=SCRIPT.replace("data,plan,None", "{k:dict(v,_price_basis_unverified=True) for k,v in data.items()},plan,None")
    app=AppTest.from_string(script,default_timeout=30).run()
    assert not app.exception
    action=next(m.value for m in app.markdown if 'dash-action' in m.value and '原始来源 USER_MANUAL' in m.value)
    assert '100–101' in action and '95' in action and '110' in action and '120' in action
    assert '复权价格尺度未核实' in action and '合格交易目标 · 未具备条件' in action
    assert not app.checkbox
    plan=dict(status='ACTIVE',direction='LONG',low=100,high=101,invalid=95,target_low=110,target_high=120,updated_at='2026-01-01T00:00:00Z')
    before=copy.deepcopy(plan)
    ready=target_readiness(plan,pd.Timestamp('2026-11-06',tz='UTC'))
    assert not ready['qualified'] and ready['risk_reward'] is None and not ready['trading_eligible']
    assert '价格尺度核验' in ready['missing'] and plan==before


def test_original_daily_selection_does_not_unlock_plan_overlay_on_native_qfq_hourly(tmp_path,payload,hourly_payload,monkeypatch):
    from test_v0441 import SCRIPT
    from desk.futu_daily import ORIGINAL
    monkeypatch.setenv('ICT_EXPERIMENT_DB',str(tmp_path/'experiment.sqlite3'))
    archive=FutuDailyArchive.create(tmp_path/'daily.sqlite3');archive.import_payload(payload)
    folder=tmp_path/'hourly';folder.mkdir()
    blob=json.dumps(hourly_payload).encode();(folder/'SPY.json').write_bytes(blob)
    (folder/'manifest.json').write_text(json.dumps(dict(symbols={'US.SPY':dict(status='PASS',sha256=hashlib.sha256(blob).hexdigest())})))
    injected=f"""
from desk.futu_daily import attach_futu,FutuDailyArchive
from desk.futu_hourly import attach_hourly
data['US.SPY']=attach_hourly(attach_futu(data['US.SPY'],FutuDailyArchive({str(archive.path)!r}),'US.SPY'),{str(folder)!r},'US.SPY')
wall=datetime(2026,11,9,12,tzinfo=ET)
"""
    app=AppTest.from_string(SCRIPT.replace('render_home(',injected+'\nrender_home('),default_timeout=30).run()
    app.radio(key='experiment_source').set_value(ORIGINAL).run()
    app.selectbox(key='experiment_period').set_value('1小时').run()
    assert not app.exception and not app.checkbox
    spec=json.loads(app.get('plotly_chart')[0].proto.spec)
    assert spec['data'][0]['name']=='1H'
    assert not any(t.get('name','').startswith('人工计划') for t in spec['data'])
