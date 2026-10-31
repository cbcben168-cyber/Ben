import time,threading
import pandas as pd
from desk.market_loader import MarketLoader


def wait(loader):
    loader.jobs.join()


def frame():
    return pd.DataFrame({'close':[100.]})


def test_two_windows_snapshot_copy_and_empty_retention():
    results=[dict(health=dict(quality='AVAILABLE',received_at='original'),minute=frame(),daily=frame()),dict(health=dict(quality='UNAVAILABLE'),minute=pd.DataFrame(),daily=pd.DataFrame())]
    calls=[]
    def fetch(c):calls.append(c);return results[min(len(calls)-1,1)]
    loader=MarketLoader(fetch)
    loader.get('US.SPY',('auto',100));wait(loader)
    loader.get('US.SPY',('manual',0));loader.get('US.SPY',('manual',1));wait(loader)
    assert len(calls)==1
    returned=loader.get('US.SPY',('auto',100));returned['minute'].iloc[0,0]=999
    assert loader.get('US.SPY',('manual',0))['minute'].iloc[0,0]==100
    loader.clear();loader.get('US.SPY',('manual',2));wait(loader)
    preserved=loader.get('US.SPY',('manual',2))
    assert preserved['health']['quality']=='STALE' and preserved['minute'].iloc[0,0]==100
    assert preserved['minute_snapshot_at']=='original'
    loader.closed.set()


def test_quote_failure_does_not_kill_reader():
    def fetch(c):
        if c=='US.VIX':raise RuntimeError('isolated')
        return dict(health=dict(quality='AVAILABLE'),minute=frame(),daily=frame())
    loader=MarketLoader(fetch)
    loader.get('US.VIX',0);loader.get('US.SPY',0);wait(loader)
    assert loader.get('US.SPY',0)['health']['quality']=='AVAILABLE'
    assert loader.get('US.VIX',0)['health']['quality']=='UNAVAILABLE'
    loader.closed.set()


def test_chart_failure_is_contained(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    from desk.store import Store
    source=dict(health=dict(quality='UNAVAILABLE',reason='测试断线',received_at='2026-10-30T00:00:00Z'),minute=pd.DataFrame(),daily=pd.DataFrame(),errors=[])
    with patch('desk.store.Store',return_value=Store(tmp_path/'p.db')),patch('desk.provider.Provider.fetch',return_value=source),patch('desk.workspace.chart_data',side_effect=ValueError('test plot error')):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run()
        assert not app.exception
        assert any('图表暂时不可用' in e.value for e in app.error)
        assert any('当前持仓' in e.value for e in app.subheader)


def test_database_read_failure_blocks_overwrite():
    import pytest
    from desk.diagnostics import SafeStore
    class Broken:
        def note(self,*args):raise OSError('test unavailable')
    safe=SafeStore(Broken())
    assert safe.note('US.SPY')==''
    with pytest.raises(ValueError):safe.note('US.SPY','must not overwrite')


def test_malformed_snapshot_keeps_worker_alive():
    loader=MarketLoader(lambda c:None if c=='US.VIX' else dict(health=dict(quality='AVAILABLE'),minute=frame(),daily=frame()))
    loader.get('US.VIX',0);loader.get('US.SPY',0);wait(loader)
    assert loader.get('US.VIX',0)['health']['quality']=='UNAVAILABLE'
    assert loader.get('US.SPY',0)['health']['quality']=='AVAILABLE'
    loader.closed.set()


def test_different_window_intervals_use_elapsed_time():
    calls=[]
    def fetch(code):
        calls.append(code)
        return dict(health=dict(quality='AVAILABLE'),minute=frame(),daily=frame())
    loader=MarketLoader(fetch)
    loader.get('US.SPY',('auto',999999,30));wait(loader)
    loader.get('US.SPY',('auto',1,60));wait(loader)
    assert len(calls)==1
    with loader.lock:loader.updated['US.SPY']-=61
    loader.get('US.SPY',('auto',1,60));wait(loader)
    assert len(calls)==2
    loader.closed.set()


def test_automatic_failure_budget_requires_explicit_reset():
    calls=[]
    def fetch(code):
        calls.append(code)
        return dict(health=dict(quality='UNAVAILABLE',reason='断线'),minute=pd.DataFrame(),daily=pd.DataFrame())
    loader=MarketLoader(fetch)
    loader.get('US.SPY',('auto',1,60));wait(loader)
    with loader.lock:
        loader.failures['US.SPY']=3;loader.updated['US.SPY']-=120
    result=loader.get('US.SPY',('auto',9,60));wait(loader)
    assert len(calls)==1 and '自动恢复已暂停' in result['health']['reason']
    loader.clear();loader.get('US.SPY',('manual',0));wait(loader)
    assert len(calls)==2
    loader.closed.set()
