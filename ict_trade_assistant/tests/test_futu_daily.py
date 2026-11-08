import copy
from datetime import datetime, timezone
import json
import sqlite3

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from desk.clock import CAL, ET
from desk.experiment import BASELINE, Experiment, completed_snapshot, replay_cutoff
from desk.futu_daily import (FutuDailyArchive, verify_payload, attach_futu, select_history,
                             FUTU, ORIGINAL, CONTRACT, digest)
from desk.market_state import market_state
from desk.ema_layers import ema_points


@pytest.fixture
def payload():
    dates = [str(t.date()) for t in CAL.sessions_in_range('2026-07-02','2026-11-06')]
    now = datetime.now(timezone.utc).isoformat()
    rows = [dict(code='US.SPY', time_key=d+' 00:00:00', open=100+i*.2, high=102+i*.2,
                 low=98+i*.2, close=101+i*.2, volume=1000+i) for i,d in enumerate(dates)]
    response = dict(request=dict(symbol='US.SPY',start=dates[0],end=dates[-1],ktype='K_DAY',
                    session='RTH',autype='QFQ',requested_at_utc=now),
                    acquired_at_utc=now,page_complete=True,records=rows)
    raw = copy.deepcopy(response);raw['request']['autype']='NONE'
    return dict(format='FUTU_DAILY_V1',provider='FUTU_OPEND',symbol='US.SPY',
                valuation_date=pd.Timestamp(now).tz_convert(ET).date().isoformat(),
                responses=dict(QFQ=response,NONE=raw),
                rehab=dict(request=dict(symbol='US.SPY',method='get_rehab',requested_at_utc=now),
                           acquired_at_utc=now,records=[]))


def test_archive_is_independent_hashed_idempotent_and_readonly(tmp_path,payload):
    path=tmp_path/'futu.sqlite3';archive=FutuDailyArchive.create(path)
    assert archive.import_payload(payload)['added']==90
    before=path.read_bytes()
    assert archive.import_payload(payload)['added']==0
    assert path.read_bytes()==before
    meta,frame=archive.read('US.SPY')
    assert meta['contract']==CONTRACT and meta['capture_sha256']==digest(payload)
    assert meta['bars']==90 and meta['last']=='2026-11-06' and meta['ict_eligible'] is False
    assert str(frame.ts.dt.tz)=='UTC' and frame.source.unique().tolist()==[CONTRACT]
    assert path.read_bytes()==before
    with sqlite3.connect(path) as db:
        assert json.loads(db.execute('SELECT payload FROM captures').fetchone()[0])==payload
    with pytest.raises(FileExistsError):FutuDailyArchive.create(path)
    with pytest.raises(ValueError):FutuDailyArchive.create(tmp_path/'updates.sqlite3')
    missing=tmp_path/'missing.sqlite3'
    with pytest.raises(sqlite3.OperationalError):FutuDailyArchive(missing).read('US.SPY')
    assert not missing.exists()


def test_same_day_conflict_and_changed_basis_are_atomic(tmp_path,payload):
    archive=FutuDailyArchive.create(tmp_path/'futu.sqlite3');archive.import_payload(payload)
    before=archive.path.read_bytes()
    changed=copy.deepcopy(payload)
    for response in changed['responses'].values():
        for key in ('open','high','low','close'):response['records'][-1][key]+=1
    with pytest.raises(ValueError,match='同日数据冲突'):archive.import_payload(changed)
    assert archive.path.read_bytes()==before
    changed=copy.deepcopy(payload);changed['responses']['QFQ']['request']['session']='ALL'
    with pytest.raises(ValueError):archive.import_payload(changed)
    changed=copy.deepcopy(payload);changed['provider']='ALPACA'
    with pytest.raises(ValueError):archive.import_payload(changed)
    assert archive.path.read_bytes()==before


def test_symbols_cannot_use_different_adjustment_valuation_dates(tmp_path,payload):
    archive=FutuDailyArchive.create(tmp_path/'futu.sqlite3');archive.import_payload(payload)
    before=archive.path.read_bytes();other=copy.deepcopy(payload);other['symbol']='US.QQQ'
    for response in other['responses'].values():
        response['request']['symbol']='US.QQQ'
        for row in response['records']:row['code']='US.QQQ'
        for target,key in [(response,'acquired_at_utc'),(response['request'],'requested_at_utc')]:
            target[key]=(pd.Timestamp(target[key])-pd.Timedelta(days=1)).isoformat()
    other['rehab']['request']['symbol']='US.QQQ'
    for target,key in [(other['rehab'],'acquired_at_utc'),(other['rehab']['request'],'requested_at_utc')]:
        target[key]=(pd.Timestamp(target[key])-pd.Timedelta(days=1)).isoformat()
    other['valuation_date']=pd.Timestamp(other['responses']['QFQ']['acquired_at_utc']).tz_convert(ET).date().isoformat()
    with pytest.raises(ValueError,match='整库复权估值日期'):archive.import_payload(other)
    assert archive.path.read_bytes()==before


@pytest.mark.parametrize('corruption', ['missing','duplicate','order','nan','ohlc','symbol','page','future','adjustment','volume'])
def test_rejects_incomplete_or_unexplained_vendor_data(payload,corruption):
    q=payload['responses']['QFQ']
    if corruption=='missing':q['records'].pop(10)
    elif corruption=='duplicate':q['records'].insert(10,copy.deepcopy(q['records'][10]))
    elif corruption=='order':q['records'].reverse()
    elif corruption=='nan':q['records'][0]['open']=float('nan')
    elif corruption=='ohlc':q['records'][0]['low']=999
    elif corruption=='symbol':q['records'][0]['code']='US.QQQ'
    elif corruption=='page':q['page_complete']=False
    elif corruption=='future':q['acquired_at_utc']='2099-01-01T00:00:00Z'
    elif corruption=='adjustment':q['records'][0]['close']+=.1
    elif corruption=='volume':q['records'][0]['volume']+=100
    with pytest.raises(ValueError):verify_payload(payload)


def split_payload(payload):
    p=copy.deepcopy(payload);p['symbol']='US.SOXX';p['rehab']['request']['symbol']='US.SOXX'
    for response in p['responses'].values():
        response['request']['symbol']='US.SOXX'
        for row in response['records']:row['code']='US.SOXX'
    for row in p['responses']['NONE']['records']:
        if row['time_key'][:10]<'2026-11-05':
            for k in ('open','high','low','close'):row[k]*=3
            row['volume']/=3
    p['rehab']['records']=[dict(ex_div_date='2026-11-05',split_base=1.,split_ert=3.,
        split_ratio=1/3,per_cash_div=None,forward_adj_factorA=.33333,forward_adj_factorB=0.)]
    return p


def test_soxx_exact_split_ohlc_and_volume_no_artificial_atr_or_trend(tmp_path,payload):
    split=split_payload(payload)
    assert verify_payload(split)['max_ohlc_error']<.000001
    archive=FutuDailyArchive.create(tmp_path/'futu.sqlite3');archive.import_payload(split)
    _,frame=archive.read('US.SOXX');cutoff=replay_cutoff(frame.ts.iloc[-1].date())
    state,_=market_state(frame,'1D',cutoff,CONTRACT)
    assert state['atr14']==pytest.approx(4.) and state['trend']=='上涨'
    assert frame.close.pct_change().abs().max()<.01
    broken=copy.deepcopy(split);broken['responses']['QFQ']['records']=copy.deepcopy(split['responses']['NONE']['records'])
    with pytest.raises(ValueError):verify_payload(broken)
    broken=copy.deepcopy(split);broken['rehab']['records']=[]
    with pytest.raises(ValueError):verify_payload(broken)


def test_dividend_reconstructed_with_raw_prior_close_not_rounded_factor(payload):
    rows=payload['responses']['NONE']['records'];ex_date='2026-09-15'
    prior=max((r for r in rows if r['time_key'][:10]<ex_date),key=lambda r:r['time_key'])
    cash=.32505;factor=1-cash/prior['close']
    payload['rehab']['records']=[dict(ex_div_date=ex_date,per_cash_div=cash,
        forward_adj_factorA=int(factor*100000)/100000,forward_adj_factorB=0.)]
    for row in payload['responses']['QFQ']['records']:
        if row['time_key'][:10]<ex_date:
            for k in ('open','high','low','close'):row[k]*=factor
    assert verify_payload(payload)['max_ohlc_error']<.000001
    payload['rehab']['records'][0]['per_cash_div']+=.1
    with pytest.raises(ValueError):verify_payload(payload)


def test_source_selection_is_whole_series_and_replay_has_no_future_prices(tmp_path,payload):
    archive=FutuDailyArchive.create(tmp_path/'futu.sqlite3');archive.import_payload(payload)
    _,frame=archive.read('US.SPY')
    old=dict(daily=frame.head(84),minute=frame.head(10),health=dict(source='OLD'),history_origin=dict(source='OLD'))
    data=attach_futu(old,archive,'US.SPY');new=select_history(data,FUTU)
    assert len(new['daily'])==90 and new['minute'].empty and new['history_origin'] is None
    assert new['_price_basis_unverified'] and new['health']['quality']=='UNAVAILABLE'
    assert len(select_history(new,ORIGINAL)['daily'])==84 and len(old['minute'])==10
    cutoff=replay_cutoff(datetime(2026,11,4).date());snapshot=completed_snapshot(new,cutoff)
    assert snapshot['daily'].ts.max()<=cutoff
    assert len(select_history(snapshot,FUTU)['daily'])==88
    actual,_=market_state(snapshot['daily'],'1D',cutoff,CONTRACT)
    poisoned=new['daily'].copy();poisoned.loc[poisoned.ts>cutoff,['open','high','low','close']]=999999.
    other,_=market_state(poisoned,'1D',cutoff,CONTRACT)
    assert actual==other
    assert market_state(frame.head(49),'1D',cutoff,CONTRACT)[0]['trend']=='UNKNOWN'
    assert ema_points(frame.head(49),'1D',cutoff,CONTRACT).empty
    absent=select_history(attach_futu(old,archive,'US.ZZZZ'),FUTU)
    assert absent['daily'].empty and absent['minute'].empty
    assert absent['coverage']['status']=='UNAVAILABLE'


def test_corrupt_archive_read_fails_closed(tmp_path,payload):
    archive=FutuDailyArchive.create(tmp_path/'futu.sqlite3');archive.import_payload(payload)
    with sqlite3.connect(archive.path) as db:
        db.execute("UPDATE bars SET qfq='{}' WHERE day='2026-11-06'")
    with pytest.raises(ValueError,match='哈希'):archive.read('US.SPY')


def test_home_futu_source_comparison_replay_and_plan_scale_block(tmp_path,payload,monkeypatch):
    from test_v0441 import SCRIPT, button, ema_traces
    archive=FutuDailyArchive.create(tmp_path/'futu.sqlite3');archive.import_payload(payload)
    monkeypatch.setenv('ICT_EXPERIMENT_DB',str(tmp_path/'experiments.sqlite3'))
    injected="""
from desk.futu_daily import attach_futu,FutuDailyArchive
data['US.SPY']=attach_futu(data['US.SPY'],FutuDailyArchive(ARCHIVE),'US.SPY')
wall=datetime(2026,11,8,12,tzinfo=ET)
""".replace('ARCHIVE',repr(str(archive.path)))
    script=SCRIPT.replace('render_home(',injected+'\nrender_home(')
    app=AppTest.from_string(script,default_timeout=40).run()
    assert not app.exception
    assert app.radio(key='experiment_source').value==FUTU
    assert len(ema_traces(app)[0]['y'])==41
    assert not app.checkbox  # No manual price overlay checkbox on an unknown scale.
    assert any('暂停叠加与风险回报计算' in m.value for m in app.markdown)
    app.selectbox(key='ema_layer_mode').set_value('对比原始EMA与实验EMA').run()
    app.slider(key='experiment_ema_short').set_value(5).run()
    traces=ema_traces(app)
    assert traces[0]['y']!=traces[2]['y']
    button(app,'恢复默认').click().run();traces=ema_traces(app)
    assert traces[0]['y']==traces[2]['y']
    app.selectbox(key='experiment_mode').set_value('历史回放').run()
    app.selectbox(key='experiment_day').set_value(datetime(2026,8,27).date()).run()
    assert not app.exception and not ema_traces(app)
    assert any('事后前复权价格' in c.value for c in app.caption)
    app.radio(key='experiment_source').set_value(ORIGINAL).run()
    assert not app.exception
