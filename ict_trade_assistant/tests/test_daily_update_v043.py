"""Synthetic updater tests; never evidence of unattended or live provider success."""
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.error
from unittest.mock import patch
import pandas as pd
import pytest
from desk.clock import CAL, ET
from desk.daily_update import DataError, LocalAlpaca, latest_completed, provider_ready, run_update, run_lock
from desk.history_import import DailyArchive
from desk.history_source import HistorySource
from desk.market_loader import MarketLoader

NOW=datetime(2026,11,4,10,tzinfo=timezone.utc)
SYMBOLS='SPY QQQ IWM SOXX SMH VOO IVV VTI VEA VUG IEFA VTV SPYM BND VXUS IEMG VGT GLD AGG IWF IJH VWO XLK'.split()


def setup(tmp_path, symbols=SYMBOLS):
    entries=[dict(symbol='US.'+s,enabled=True) for s in symbols]
    legacy={e['symbol']:dict(daily=[dict(ts='2026-11-02T00:00:00-05:00',open=100,high=102,low=99,close=101,volume=10,eligible=True,session='RTH')],minute=[],health=dict(quality='STALE')) for e in entries}
    return entries,legacy,DailyArchive(tmp_path/'base.sqlite3')


class FakeData:
    def __init__(self,fail=None,empty=False,forming=False):self.calls=[];self.fail=fail;self.empty=empty;self.forming=forming
    def preflight(self):return dict(configured=True,status='SYNTHETIC_TEST_ONLY',sip_permission='NOT_VERIFIED',rate_limit='UNKNOWN',unattended_proven=False)
    def fetch(self,symbol,start,end):
        self.calls.append((symbol,start,end))
        if symbol==self.fail:raise DataError('PROVIDER_NETWORK_OR_RESPONSE_ERROR')
        ticker=symbol[3:]
        dates=CAL.sessions_in_range(pd.Timestamp(start).date(),(pd.Timestamp(end)-pd.Timedelta(microseconds=1)).date())
        bars=[] if self.empty else [dict(symbol=ticker,timestamp=pd.Timestamp(str(d.date()),tz=ET).isoformat(),open=100,high=102,low=99,close=101,volume=10) for d in dates]
        if self.forming:bars[0]['timestamp']='2026-11-04T00:00:00-05:00'
        return dict(tool='get_stock_bars',request=dict(symbols=[ticker],timeframe='1Day',feed='sip',adjustment='raw',start=start,end=end),bars={ticker:bars})


def test_23_symbols_incremental_and_idempotent(tmp_path):
    entries,legacy,base=setup(tmp_path);client=FakeData()
    r=run_update(tmp_path/'updates',entries,legacy,base,client,NOW,sleep=lambda _:None,interval=0)
    assert r['status']=='COMPLETE' and r['added']==23 and r['requests']==23
    assert all('2026-11-03' in start and '2026-11-04' in end for _,start,end in client.calls)
    assert not r['unattended_proven']
    r2=run_update(tmp_path/'updates',entries,legacy,base,client,NOW,sleep=lambda _:None,interval=0)
    assert r2['requests']==0 and r2['added']==0 and len(client.calls)==23
    assert len(DailyArchive(tmp_path/'updates/updates.sqlite3').coverage())==23


def test_one_failure_continues_other_22_and_retries_are_bounded(tmp_path):
    entries,legacy,base=setup(tmp_path);client=FakeData(fail='US.SPY')
    r=run_update(tmp_path/'updates',entries,legacy,base,client,NOW,sleep=lambda _:None,interval=0)
    assert r['status']=='PARTIAL' and r['added']==22 and r['requests']==25
    assert sum(s=='US.SPY' for s,_,_ in client.calls)==3
    assert r['rows'][0]['reason']=='PROVIDER_NETWORK_OR_RESPONSE_ERROR'
    assert r['rows'][-1]['status']=='UPDATED'


def test_provider_delay_does_not_store_empty_or_open_days(tmp_path):
    entries,legacy,base=setup(tmp_path,['SPY']);client=FakeData(empty=True)
    r=run_update(tmp_path/'updates',entries,legacy,base,client,NOW,sleep=lambda _:None,interval=0)
    assert r['requests']==3 and r['added']==0 and r['rows'][0]['status']=='PENDING_PROVIDER_DATA'
    client=FakeData()
    r=run_update(tmp_path/'early',entries,legacy,base,client,datetime(2026,11,3,22,30,tzinfo=timezone.utc),sleep=lambda _:None)
    assert r['requests']==0 and r['rows'][0]['status']=='PENDING_PROVIDER_DATA'
    assert not provider_ready('2026-11-03',datetime(2026,11,3,22,30,tzinfo=timezone.utc))


@pytest.mark.parametrize('now,expected',[
 ('2026-11-26T17:00:00Z','2026-11-25'),
 ('2026-11-27T18:01:00Z','2026-11-25'),
 ('2026-11-27T18:02:00Z','2026-11-27'),
 ('2026-03-06T21:02:00Z','2026-03-06'),
 ('2026-03-09T20:02:00Z','2026-03-09')])
def test_exchange_calendar_early_close_and_dst(now,expected):
    assert latest_completed(pd.Timestamp(now))==expected


def test_forming_bar_is_rejected_and_records_remain_missing(tmp_path):
    entries,legacy,base=setup(tmp_path,['SPY'])
    r=run_update(tmp_path/'updates',entries,legacy,base,FakeData(forming=True),NOW,sleep=lambda _:None)
    assert r['added']==0 and r['rows'][0]['reason']=='IMPORT_VALIDATION_OR_CONFLICT_REJECTED'


def test_no_credentials_means_zero_http_and_blocked_not_automation(tmp_path,monkeypatch):
    monkeypatch.delenv('APCA_API_KEY_ID',raising=False);monkeypatch.delenv('APCA_API_SECRET_KEY',raising=False)
    entries,legacy,base=setup(tmp_path)
    with patch('urllib.request.urlopen',side_effect=AssertionError('No HTTP without credentials')):
        r=run_update(tmp_path/'updates',entries,legacy,base,now=NOW)
    assert r['status']=='BLOCKED' and r['requests']==0 and not r['unattended_proven']
    assert all(x['status']=='BLOCKED' for x in r['rows'])


def test_no_new_completed_session_exits_without_provider_or_credentials(tmp_path,monkeypatch):
    monkeypatch.delenv('APCA_API_KEY_ID',raising=False);monkeypatch.delenv('APCA_API_SECRET_KEY',raising=False)
    entries,legacy,base=setup(tmp_path,['SPY'])
    with patch('urllib.request.urlopen',side_effect=AssertionError('No new session, no request')):
        r=run_update(tmp_path/'updates',entries,legacy,base,now=datetime(2026,11,3,12,tzinfo=timezone.utc))
    assert r['target']=='2026-11-02' and r['status']=='COMPLETE' and r['requests']==0


def test_concurrent_run_does_not_replace_active_result(tmp_path):
    entries,legacy,base=setup(tmp_path,['SPY']);root=tmp_path/'updates'
    with run_lock(root):
        r=run_update(root,entries,legacy,base,FakeData(),NOW)
        assert r['reason']=='RUN_ALREADY_ACTIVE' and not (root/'latest.json').exists()


def test_credentials_are_not_logged_and_client_is_market_data_only(monkeypatch):
    monkeypatch.setenv('APCA_API_KEY_ID','DUMMY_KEY_FOR_TEST');monkeypatch.setenv('APCA_API_SECRET_KEY','DUMMY_SECRET_FOR_TEST')
    def reject(req,timeout):
        assert req.full_url.startswith('https://data.alpaca.markets/v2/stocks/bars?')
        raise urllib.error.URLError('DUMMY_SECRET_FOR_TEST')
    with patch('urllib.request.urlopen',side_effect=reject):
        with pytest.raises(DataError) as error:LocalAlpaca().fetch('US.SPY','2026-11-03T00:00:00-05:00','2026-11-04T00:00:00-05:00')
    assert 'DUMMY' not in str(error.value)


def test_update_cache_revision_refreshes_without_merging_original_prices(tmp_path):
    entries,legacy,base=setup(tmp_path,['SPY']);file=tmp_path/'legacy.json';file.write_text(json.dumps(legacy),encoding='utf8')
    updates=DailyArchive(tmp_path/'updates.sqlite3')
    source=HistorySource(file,datetime(2026,10,29,16,2,tzinfo=ET),base,updates)
    loader=MarketLoader(source.fetch)
    try:
        loader.get('US.SPY',0);loader.jobs.join()
        assert 'independent_daily' not in loader.get('US.SPY',0)
        payload=FakeData().fetch('US.SPY','2026-11-03T00:00:00-05:00','2026-11-04T00:00:00-05:00')
        updates.import_payload(payload,'SPY',NOW.isoformat())
        loader.get('US.SPY',0);loader.jobs.join();d=loader.get('US.SPY',0)
        assert len(d['daily'])==1 and d['daily'].ts.iloc[0].date().isoformat()=='2026-11-02'
        assert d['independent_daily'].ts.iloc[0].date().isoformat()=='2026-11-03'
        assert d['independent_coverage']['adjustment']=='raw'
    finally:loader.closed.set()


def test_same_day_conflict_and_adjustment_mismatch_reject_without_overwrite(tmp_path):
    archive=DailyArchive(tmp_path/'updates.sqlite3')
    payload=FakeData().fetch('US.SPY','2026-11-03T00:00:00-05:00','2026-11-04T00:00:00-05:00')
    archive.import_payload(payload,'SPY',NOW.isoformat());revision=archive.revision('US.SPY')
    payload['bars']['SPY'][0]['close']=102
    with pytest.raises(ValueError,match='冲突'):archive.import_payload(payload,'SPY',NOW.isoformat())
    payload['request']['adjustment']='all'
    with pytest.raises(ValueError,match='复权'):archive.import_payload(payload,'SPY',NOW.isoformat())
    assert archive.revision('US.SPY')==revision and archive.read('US.SPY')[1].close.iloc[0]==101


def test_original_etf_update_chart_is_separate_and_live_ict_stays_disabled(tmp_path):
    from streamlit.testing.v1 import AppTest
    from desk.store import Store
    entries,legacy,base=setup(tmp_path,['SPY'])
    file=tmp_path/'legacy.json';file.write_text(json.dumps(legacy),encoding='utf8')
    updates=DailyArchive(tmp_path/'updates.sqlite3')
    payload=FakeData().fetch('US.SPY','2026-11-03T00:00:00-05:00','2026-11-04T00:00:00-05:00')
    updates.import_payload(payload,'SPY',NOW.isoformat())
    source=HistorySource(file,datetime(2026,11,4,5,0,tzinfo=ET),base,updates)
    store=Store(tmp_path/'users.sqlite3')
    with patch('desk.store.Store',return_value=store),patch('desk.provider.Provider.fetch',lambda self,c:source.fetch(c)):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
        next(r for r in app.radio if r.label=='周期').set_value('1D').run()
        assert not app.exception
        spec=json.loads(next(c.proto.spec for c in app.get('plotly_chart') if c.proto.id.endswith('-mainchart')))
        assert len(spec['data'][0]['x'])==1 and spec['data'][0]['x'][0].startswith('2026-11-03')
        next(r for r in app.radio if r.label=='日线资料来源').set_value('原历史档案（保留）').run()
        spec=json.loads(next(c.proto.spec for c in app.get('plotly_chart') if c.proto.id.endswith('-mainchart')))
        assert len(spec['data'][0]['x'])==1 and spec['data'][0]['x'][0].startswith('2026-11-02')
        assert next(x for x in app.checkbox if x.label.startswith('实时ICT')).disabled
