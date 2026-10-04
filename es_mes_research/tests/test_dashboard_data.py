import json
import socket
import threading
import time
import httpx
import pandas as pd
from fastapi.testclient import TestClient
from es_mes import dashboard_data
from es_mes.dashboard import create_api
from es_mes.dashboard_data import project,events_from


def fixture_events(tmp_path):
    folder=tmp_path/'artifacts/forward/2026-10-02';folder.mkdir(parents=True)
    pos=dict(entry_received_at_utc='2026-10-02T13:45:03Z',entry_price=6002.25,stop=6000.5,target=6007.5,direction=1)
    meta=dict(product='ES',contract='US.ES2612',quantity=1,fee_usd=4.,slippage_ticks=1)
    events=[dict(kind='QUOTE',quote_time_utc='2026-10-02T13:45:09Z',last_price=6003.,received_at_utc='2026-10-02T13:45:09Z'),
            dict(kind='ENTRY_PROXY',position=pos,received_at_utc=pos['entry_received_at_utc'],**meta),
            dict(kind='EXIT_PROXY',position=pos,exit_price=6007.5,net_usd=258.5,reason='TARGET',received_at_utc='2026-10-02T13:45:09Z',**meta)]
    (folder/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events)+'\n',encoding='utf-8')
    pd.DataFrame([dict(ts='2026-10-02T13:30:00Z',open=6000,high=6001,low=5999,close=6000,volume=10)]).to_csv(folder/'completed_bars.csv',index=False)
    return events,pos,folder


def test_projection_preserves_actual_records_and_unknowns(tmp_path,monkeypatch):
    events,pos,folder=fixture_events(tmp_path)
    monkeypatch.setattr(dashboard_data,'now',lambda:pd.Timestamp('2026-10-02T13:45:10Z'))
    result=project(tmp_path,{})
    assert result['metrics']['realized_net_usd']==258.5
    trade=result['trades'][0]
    assert trade['entry_price']==6002.25 and trade['exit_price']==6007.5
    assert trade['fee_usd']==4 and trade['quantity']==1
    assert result['markers'][0]['price']==trade['entry_price']
    assert result['markers'][1]['price']==trade['exit_price']
    assert not result['quote']['stale']
    assert result['opening'] is None  # Never guess the opening range from partial bars.
    events[-1]=dict(kind='POSITION_INVALIDATED',position=pos,reason='DATA_FAILURE',received_at_utc='2026-10-02T13:45:09Z')
    (folder/'events.jsonl').write_text('\n'.join(json.dumps(e) for e in events),encoding='utf-8')
    result=project(tmp_path,{})
    assert result['metrics']['realized_net_usd'] is None
    assert result['metrics']['invalid']==1 and result['trades'][0]['status']=='INVALID'


def test_stale_position_valuation_and_history(tmp_path,monkeypatch):
    events,pos,folder=fixture_events(tmp_path)
    monkeypatch.setattr(dashboard_data,'now',lambda:pd.Timestamp('2026-10-02T13:45:10Z'))
    state=dict(position=pos,config=dict(product='ES'),last_quote_utc='2026-10-02T13:45:09Z',last_price=6003.)
    assert project(tmp_path,state)['metrics']['unrealized_gross_usd']==37.5
    state['last_quote_utc']='2026-10-02T13:44:00Z'
    assert project(tmp_path,state)['metrics']['unrealized_gross_usd'] is None
    monkeypatch.setattr(dashboard_data,'now',lambda:pd.Timestamp('2026-10-03T13:45:10Z'))
    assert project(tmp_path,state,'2026-10-02')['position'] is None


def test_csv_exports_no_fake_data_and_bad_paths(tmp_path):
    fixture_events(tmp_path)
    with TestClient(create_api(tmp_path),base_url='http://127.0.0.1:8765') as client:
        csv=client.get('/download/2026-10-02/trades')
        assert csv.status_code==200 and '6002.25' in csv.text and '258.5' in csv.text
        assert 'attachment' in csv.headers['content-disposition']
        assert client.get('/download/2026-10-01/report').status_code==404
        assert client.get('/api/dashboard?date=2026-99-99').status_code==400
        assert client.get('/api/dashboard?date=2026-10-01').json()['view']['trades']==[]
        token=client.get('/session').json()['token']
        headers={'Origin':'http://127.0.0.1:8765','X-CSRF-Token':token}
        response=client.post('/action',headers=headers,json=dict(action='choose',option='KEEP_FROZEN',session_date='2026-10-02'))
        assert response.status_code==200
        assert client.get('/api/dashboard?date=2026-10-02').json()['view']['latest_choice']=='KEEP_FROZEN'
        assert client.get('/api/dashboard?date=2026-10-01').json()['view']['latest_choice'] is None


def test_partial_tail_tolerated_but_corrupt_middle_rejected(tmp_path):
    import pytest
    file=tmp_path/'events.jsonl';file.write_text('{"kind":"QUOTE"}\n{"ki',encoding='utf-8')
    assert len(events_from(file))==1
    file.write_text('BROKEN\n{"kind":"QUOTE"}',encoding='utf-8')
    with pytest.raises(ValueError,match='LOG_INVALID'):events_from(file)


def test_sse_delivers_new_state_without_page_reload(tmp_path):
    import uvicorn
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    api=create_api(tmp_path,port)
    server=uvicorn.Server(uvicorn.Config(api,host='127.0.0.1',port=port,log_level='error'))
    thread=threading.Thread(target=server.run,daemon=True);thread.start()
    try:
        for _ in range(50):
            if server.started:break
            time.sleep(.05)
        assert server.started
        with httpx.stream('GET',f'http://127.0.0.1:{port}/api/stream',timeout=5) as response:
            lines=(line for line in response.iter_lines() if line.startswith('data: '))
            first=json.loads(next(lines)[6:]);assert first['forward']['status']=='STOPPED'
            api.state.service.forward.state['status']='WAITING_CASH_SESSION'
            second=json.loads(next(lines)[6:]);assert second['forward']['status']=='WAITING_CASH_SESSION'
    finally:server.should_exit=True;thread.join(timeout=5)
    assert not thread.is_alive()
