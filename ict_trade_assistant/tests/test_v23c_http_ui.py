from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from streamlit.testing.v1 import AppTest

from test_v23c_signals import request, fill, NOW


def post(url,payload,token='x'*40):
    req=Request(url,data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urlopen(req,timeout=4) as r: return json.loads(r.read())


def test_receiver_auth_and_simulation_transport_are_real_http(tmp_path):
    from desk.v23c_receiver import server
    from desk.v23c_signals import SignalStore
    store=SignalStore(tmp_path/'events.sqlite3')
    http=server(store,'x'*40,port=0,simulation=True)
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    url='http://127.0.0.1:'+str(http.server_port)+'/v23c/events'
    try:
        with pytest.raises(HTTPError) as error: post(url,request(),token='wrong')
        assert error.value.code==401 and store.read()==[]
        accepted=post(url,request())
        assert accepted['quality']=='SIMULATION' and not accepted['trading_eligible']
        assert post(url,request())['duplicate'] and len(store.read())==1
        with pytest.raises(HTTPError) as error: post(url,dict(request(),secret='do-not-store'))
        assert error.value.code==400 and len(store.read())==1
    finally:
        http.shutdown();http.server_close();thread.join(timeout=2)


def test_receiver_never_binds_protected_services(tmp_path):
    from desk.v23c_receiver import server
    from desk.v23c_signals import SignalStore
    store=SignalStore(tmp_path/'events.sqlite3')
    for port in (8501,8506,8527):
        with pytest.raises(ValueError,match='PROTECTED'): server(store,'x'*40,port)


def test_dashboard_empty_does_not_create_database_or_claim_phone_delivery(tmp_path,monkeypatch):
    path=tmp_path/'missing.sqlite3'
    monkeypatch.setenv('ICT_V23C_SIGNAL_DB',str(path))
    app=AppTest.from_string('from desk.v23c_ui import render\nrender()').run(timeout=20)
    assert not app.exception and not path.exists()
    texts=' '.join(x.value for x in app.info)+ ' '.join(x.value for x in app.caption)
    assert '尚未收到' in texts and '手机' in texts


def test_dashboard_separates_requests_simulated_fills_and_test_data(tmp_path,monkeypatch):
    from desk.v23c_signals import SignalStore
    path=tmp_path/'signals.sqlite3';store=SignalStore(path)
    store.ingest(request(),NOW,simulation=True)
    store.ingest(fill(),datetime(2026,11,16,14,30,10,tzinfo=timezone.utc),simulation=True)
    monkeypatch.setenv('ICT_V23C_SIGNAL_DB',str(path))
    before=path.read_bytes()
    app=AppTest.from_string('from desk.v23c_ui import render\nrender()').run(timeout=20)
    assert not app.exception
    text=' '.join(x.value for x in app.markdown)+ ' '.join(x.value for x in app.caption)
    assert '隔离样本' in text and '模拟成交' in text and '真实账户' in text
    assert path.read_bytes()==before
