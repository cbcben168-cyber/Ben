"""Dynamic universe tests. Positive-data cases are synthetic engineering tests only."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch
import pandas as pd
import pytest
from desk.clock import ET
from desk.decision import prioritize
from desk.history_source import HistorySource, missing_history
from desk.market_loader import MarketLoader
from desk.observations import build_observation, ranked, SYMBOLS
from desk.store import Store, DEFAULTS
from desk.watchlist import TOP20, PRESET, normalize_symbol


@pytest.mark.parametrize('value,expected',[('smh','US.SMH'),('US.aapl','US.AAPL'),(' BRK.B ','US.BRK.B')])
def test_code_normalization(value,expected):
    assert normalize_symbol(value)==expected


@pytest.mark.parametrize('code',['VIX','US.VIX','','HK.00700/','SPY;delete'])
def test_background_and_invalid_codes_rejected(code):
    with pytest.raises(ValueError):normalize_symbol(code)


def test_add_disable_enable_delete_and_plan_preservation(tmp_path):
    path=tmp_path/'desk.db';s=Store(path)
    assert s.manage_watchlist('add','smh',group='半导体')==1
    assert s.manage_watchlist('add','US.SMH')==0
    s.manage_watchlist('update','SMH',group='半导体',enabled=False)
    assert 'US.SMH' not in s.settings()['watchlist']
    assert Store(path).settings()['watchlist_entries'][-1]==dict(symbol='US.SMH',enabled=False,group='半导体')
    s.manage_watchlist('update','SMH',group='半导体',enabled=True)
    assert 'US.SMH' in Store(path).settings()['watchlist']
    ident,_=s.save_plan(dict(symbol='US.SMH',strategy_version='SYNTHETIC_TEST_ONLY',direction='LONG',low=99,high=100,invalid=98,target_low=105,target_high=106,memo='保留'))
    s.manage_watchlist('delete','SMH')
    assert 'US.SMH' not in Store(path).settings()['watchlist']
    assert s.plans('US.SMH')[0]['plan_id']==ident


def test_preset_import_is_additive_idempotent_and_has_provenance(tmp_path):
    s=Store(tmp_path/'desk.db');s.manage_watchlist('add','SMH',group='我的半导体')
    s.manage_watchlist('update','SPY',enabled=False,group='我的核心')
    assert s.manage_watchlist('import_top20')==18
    assert s.manage_watchlist('import_top20')==0
    saved=Store(s.path).settings();entries=saved['watchlist_entries']
    assert len(entries)==23 and len({e['symbol'] for e in entries})==23
    assert next(e for e in entries if e['symbol']=='US.SPY')==dict(symbol='US.SPY',enabled=False,group='我的核心')
    assert next(e for e in entries if e['symbol']=='US.SMH')['group']=='我的半导体'
    assert set(TOP20).issubset({e['symbol'] for e in entries})
    assert saved['watchlist_presets'][PRESET['id']]==PRESET


def test_more_than_twenty_concurrent_import_and_no_reseed_after_delete(tmp_path):
    s=Store(tmp_path/'desk.db')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i:s.manage_watchlist('add','ETF'+str(i)),range(25)))
    assert len(s.settings()['watchlist'])==29
    for code in list(s.settings()['watchlist']):s.manage_watchlist('delete',code)
    assert Store(s.path).settings()['watchlist']==[]


def test_dynamic_fifth_data_and_missing_data_cannot_rank(market_fixture):
    now=datetime(2026,10,30,8,tzinfo=ET)
    symbols=(*SYMBOLS,'US.SMH','US.AAPL','US.VIX')
    observations={c:build_observation(c,market_fixture,DEFAULTS,now,dict(low=99,high=101)) for c in symbols}
    observations['US.AAPL']=build_observation('US.AAPL',missing_history('US.AAPL',now),DEFAULTS,now)
    assert [r['symbol'] for r in prioritize(observations,{},now)]==list(SYMBOLS)
    rows=prioritize(observations,{},now,symbols=symbols+('US.SMH',))
    qualified=[r for r in rows if r['qualification']<2 and r['focus']][:5]
    assert len(qualified)==5 and len({r['symbol'] for r in qualified})==5
    assert 'US.SMH' in {r['symbol'] for r in qualified}
    assert 'US.AAPL' not in {r['symbol'] for r in qualified}
    missing=next(r for r in rows if r['symbol']=='US.AAPL')
    assert missing['stage']=='UNKNOWN' and missing['focus'] is None and not missing['live_review']
    assert len(ranked(observations,symbols=symbols))==5


def test_local_history_is_lazy_per_symbol_and_missing_is_explicit(tmp_path,market_fixture):
    now=datetime(2026,10,30,8,tzinfo=ET)
    data=deepcopy(market_fixture)
    for p in ('minute','daily'):data[p]=data[p].to_dict('records')
    file=tmp_path/'history.json';file.write_text(json.dumps({'US.SPY':data,'US.VIX':{'minute':[],'daily':[]}},default=str),encoding='utf-8')
    source=HistorySource(file,now)
    assert not source.cache
    absent=source.fetch('US.SMH');assert absent['terminal_missing'] and absent['minute'].empty
    assert source.fetch('US.VIX')['terminal_missing']
    assert '历史数据待加载' in absent['health']['reason']
    assert not source.cache
    saved=source.fetch('US.SPY');assert list(source.cache)==['US.SPY']
    assert saved['health']['quality']=='STALE' and saved['health']['source']=='SYNTHETIC_TEST_ONLY'
    saved['minute'].iloc[0,1]=999
    assert source.fetch('US.SPY')['minute'].iloc[0,1]!=999


def test_bounded_nonblocking_queue_and_terminal_missing_cache():
    release=threading.Event();calls=[]
    now=datetime(2026,10,30,8,tzinfo=ET)
    def fetch(code):
        calls.append(code);release.wait(2)
        return missing_history(code,now)
    loader=MarketLoader(fetch,max_pending=3)
    try:
        start=time.monotonic()
        for i in range(40):loader.get('US.ETF'+str(i),('manual',0),wait=0)
        assert time.monotonic()-start<.5 and len(loader.pending)==3
        assert len(calls)<=1 and loader.jobs.qsize()<=3
        release.set();loader.jobs.join()
        count=len(calls)
        for _ in range(20):
            for code in list(loader.results):
                loader.updated[code]=0;loader.retry_at[code]=0
                assert loader.get(code,('auto',100,30),wait=0)['terminal_missing']
        assert len(calls)==count
    finally:
        release.set();loader.closed.set()


def test_fifth_symbol_full_chart_sop_workflow_with_synthetic_data(tmp_path,market_fixture):
    from streamlit.testing.v1 import AppTest
    s=Store(tmp_path/'desk.db');s.manage_watchlist('add','SMH')
    now=datetime(2026,10,30,8,tzinfo=ET)
    with patch('desk.store.Store',return_value=s),patch('desk.provider.Provider.fetch',return_value=market_fixture),patch('desk.workspace.now_et',return_value=now):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
        next(x for x in app.selectbox if x.label=='独立窗口观察标的').select('US.SMH').run()
        assert not app.exception
        spec=json.loads(app.get('plotly_chart')[0].proto.spec)
        assert spec['data'][0]['type']=='candlestick'
        assert any('下一条件：' in x.value for x in app.markdown)
        assert len([b for b in app.button if b.key and b.key.startswith('pick_')])==5
        assert next(x for x in app.checkbox if x.label.startswith('实时ICT')).disabled


def test_disabled_and_deleted_symbols_are_not_fetched_or_ranked(tmp_path,market_fixture):
    from streamlit.testing.v1 import AppTest
    s=Store(tmp_path/'desk.db')
    s.manage_watchlist('delete','SOXX')
    s.manage_watchlist('update','IWM',enabled=False)
    calls=[]
    def fetch(self,code):
        calls.append(code)
        return market_fixture
    with patch('desk.store.Store',return_value=s),patch('desk.provider.Provider.fetch',fetch),patch('desk.workspace.now_et',return_value=datetime(2026,10,30,8,tzinfo=ET)):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
        choices=next(x for x in app.selectbox if x.label=='独立窗口观察标的')
        assert 'US.IWM' in choices.options and 'US.SOXX' not in choices.options
        choices.select('US.IWM').run()
        assert not app.exception
        assert not {'US.IWM','US.SOXX'} & set(calls)
        assert any('证券已停用' in x.value for x in app.error)
        assert not any(b.key and (b.key.startswith('pick_US.IWM_') or b.key.startswith('pick_US.SOXX_')) for b in app.button)
