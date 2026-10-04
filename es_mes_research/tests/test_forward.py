import json
import threading
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pandas as pd
import pytest
from es_mes import forward
from es_mes.core import calendar
from es_mes.forward import Forward,prepare,signal,fresh
from es_mes.dashboard import App,create_api
from fastapi.testclient import TestClient


@pytest.fixture
def sample():
    day=calendar('2026-10-02','2026-10-02').iloc[0]
    stamps=pd.date_range(day.open,periods=15,freq='min')
    bars=pd.DataFrame(dict(time_key=stamps.tz_convert('America/New_York').strftime('%Y-%m-%d %H:%M:%S'),open=6000.,high=6001.,low=5999.,close=6000.,volume=10))
    bars.loc[14,['high','close']]=6002.
    return day,bars


def setup_runner(tmp_path,day,monkeypatch):
    runner=Forward(tmp_path)
    runner.config=dict(product='ES',contract='US.ES2612',timezone='America/New_York',fee=4.,slip=1)
    runner.session=day.name.strftime('%Y-%m-%d');runner.eligible=True
    monkeypatch.setattr(forward,'now',lambda:day.open+pd.Timedelta(minutes=15,seconds=3))
    return runner


def quote(at,price):
    local=at.tz_convert('America/New_York')
    return dict(data_date=local.strftime('%Y-%m-%d'),data_time=local.strftime('%H:%M:%S'),last_price=price)


def test_signal_and_prefix_quality(sample):
    day,bars=sample;at=day.open+pd.Timedelta(minutes=15,seconds=3)
    good=prepare(bars,'America/New_York',day,at)
    assert signal(good,day)['stop']==6000.5
    assert signal(good,day)['direction']==1
    assert len(prepare(bars,'America/New_York',day,at-pd.Timedelta(seconds=3)))==14
    with pytest.raises(ValueError,match='MISSING'):prepare(bars.drop(index=3),'America/New_York',day,at)
    with pytest.raises(ValueError,match='MISSING'):prepare(pd.concat([bars,bars.iloc[:1]]),'America/New_York',day,at)


def test_proxy_entry_exit_costs_and_one_trade(sample,tmp_path,monkeypatch):
    day,bars=sample;r=setup_runner(tmp_path,day,monkeypatch);at=day.open+pd.Timedelta(minutes=15,seconds=3)
    r.tick(bars,quote(at,6002.),at,day)
    assert r.position['entry_price']==6002.25
    assert r.position['target']==6007.5
    at+=pd.Timedelta(seconds=3);r.tick(bars,quote(at,6000.25),at,day)
    exit_event=[e for e in r.events if e['kind']=='EXIT_PROXY'][0]
    assert exit_event['net_usd']==pytest.approx(-116.5)
    at+=pd.Timedelta(seconds=3);r.tick(bars,quote(at,6002),at,day)
    assert r.position is None
    assert len([e for e in r.events if e['kind']=='ENTRY_PROXY'])==1
    restored=Forward(tmp_path);assert restored.seen
    r.report(day.name.strftime('%Y-%m-%d'))
    folder=tmp_path/'artifacts/forward'/day.name.strftime('%Y-%m-%d')
    assert (folder/'report.md').exists()
    choices=(folder/'optimization_choices.csv').read_text(encoding='utf-8');r.report(day.name.strftime('%Y-%m-%d'))
    assert (folder/'optimization_choices.csv').read_text(encoding='utf-8')==choices


@pytest.mark.parametrize('mode',['late','paused','stale','gap'])
def test_fail_closed(sample,tmp_path,monkeypatch,mode):
    day,bars=sample;r=setup_runner(tmp_path,day,monkeypatch);at=day.open+pd.Timedelta(minutes=15,seconds=3)
    if mode=='late':at+=pd.Timedelta(seconds=20)
    if mode=='paused':r.state['paused']=True
    if mode=='gap':r.previous_quote=at-pd.Timedelta(seconds=20)
    if mode=='stale':
        with pytest.raises(ValueError,match='STALE'):r.tick(bars,quote(at-pd.Timedelta(seconds=20),6002),at,day)
    else:r.tick(bars,quote(at,6002),at,day)
    assert r.position is None


def test_gap_invalidates_position(sample,tmp_path,monkeypatch):
    day,bars=sample;r=setup_runner(tmp_path,day,monkeypatch);at=day.open+pd.Timedelta(minutes=15,seconds=3)
    r.tick(bars,quote(at,6002),at,day)
    at+=pd.Timedelta(seconds=20);r.tick(bars,quote(at,6003),at,day)
    assert r.position is None
    assert any(e['kind']=='POSITION_INVALIDATED' for e in r.events)
    assert not any(e['kind']=='EXIT_PROXY' for e in r.events)


def test_recovery_blocks_restart(tmp_path):
    (tmp_path/'state').mkdir()
    (tmp_path/'state/forward_checkpoint.json').write_text(json.dumps(dict(position={'direction':1},state={},session='2026-10-02',seen=True)))
    r=Forward(tmp_path)
    with pytest.raises(ValueError,match='UNRESOLVED'):r.start({})


def test_local_web_security_and_allowlist(tmp_path):
    api=create_api(tmp_path,8765)
    with TestClient(api,base_url='http://127.0.0.1:8765') as client:
        assert not client.get('/status').json()['orders_enabled']
        assert client.post('/action',json={'action':'pause'}).status_code==403
        token=client.get('/session').json()['token']
        headers={'Origin':'http://127.0.0.1:8765','X-CSRF-Token':token}
        assert client.post('/action',json={'action':'pause'},headers=headers).status_code==200
        assert api.state.service.forward.state['paused']
        assert client.post('/action',json={'action':'shell'},headers=headers).status_code==422
        assert client.get('/status',headers={'Host':'evil.example'}).status_code==403
        assert client.get('/session',headers={'Origin':'http://evil.example'}).status_code==403
        assert client.post('/action',json={'action':'start','slip':1.5},headers=headers).status_code==422
        assert client.get('/api/dashboard?date=../../secret').status_code==400
        assert client.get('/assets/app.js').status_code==200


def test_start_requires_real_permission(tmp_path):
    app=App(tmp_path)
    with pytest.raises(ValueError,match='PERMISSIONS'):app.action('start',dict(product='ES'))
    with pytest.raises(ValueError,match='ACTION'):app.action('trade',{})
    with pytest.raises(ValueError,match='OPTION'):app.action('choose',dict(option='AUTO_OPTIMIZE'))


def test_freshness_no_future_quote():
    t=pd.Timestamp('2026-10-02T14:00:00Z')
    assert fresh(t,t+pd.Timedelta(seconds=10))
    assert not fresh(t,t-pd.Timedelta(seconds=1))
