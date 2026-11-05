"""Synthetic validation fixtures; actual market coverage is audited separately."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest
from desk.clock import ET
from desk.history_import import DailyArchive
from desk.history_source import HistorySource
from desk.history_ui import coverage_rows
from desk.market_loader import MarketLoader
from desk.observations import build_observation
from desk.store import Store, DEFAULTS
from desk.decision import prioritize


ACQUIRED='2026-07-10T20:05:00+00:00'


def response(days=('06','07','08'),start='06',end='09'):
    return dict(tool='get_stock_bars',request=dict(symbols=['SMH'],timeframe='1Day',feed='sip',
        start=f'2026-07-{start}T00:00:00-04:00',end=f'2026-07-{end}T00:00:00-04:00'),
        bars={'SMH':[dict(symbol='SMH',timestamp=f'2026-07-{day}T04:00:00Z',open=100,high=103,low=99,close=101,volume=10) for day in days]})


def test_incremental_idempotent_persistent_and_no_filled_days(tmp_path):
    a=DailyArchive(tmp_path/'daily.db')
    first=a.import_payload(response(('06',)), 'SMH', ACQUIRED)
    assert first['status']=='DAILY_PARTIAL' and first['missing']==['2026-07-07','2026-07-08']
    assert first['chart_ready'] and not first['daily_observation_eligible']
    second=a.import_payload(response(('07','08'),start='07'), 'SMH', ACQUIRED)
    assert second['added']==2 and second['bars']==3 and second['missing']==[]
    assert a.import_payload(response(),'SMH',ACQUIRED)['added']==0
    meta,frame=DailyArchive(a.path).read('US.SMH')
    assert meta['daily_observation_eligible'] and not meta['ict_eligible']
    assert meta['feed']=='sip' and meta['acquired_at']==ACQUIRED
    assert (frame.session=='VENDOR_DAY').all() and len(frame)==3


@pytest.mark.parametrize('damage',['duplicate','price','nan','volume','naive','label','symbol','future','period','feed'])
def test_bad_import_rejected_without_losing_previous_data(tmp_path,damage):
    a=DailyArchive(tmp_path/'daily.db');a.import_payload(response(),'SMH',ACQUIRED)
    payload=response();row=payload['bars']['SMH'][0];acquired=ACQUIRED
    if damage=='duplicate':payload['bars']['SMH'].append(deepcopy(row))
    elif damage=='price':row['low']=200
    elif damage=='nan':row['close']=float('nan')
    elif damage=='volume':row['volume']=-1
    elif damage=='naive':row['timestamp']='2026-07-06T00:00:00'
    elif damage=='label':row['timestamp']='2026-07-06T05:00:00Z'
    elif damage=='symbol':row['symbol']='SPY'
    elif damage=='future':acquired='2026-07-06T12:00:00Z'
    elif damage=='period':payload['request']['timeframe']='1Min'
    elif damage=='feed':payload['request']['feed']='iex'
    revision=a.revision('US.SMH')
    with pytest.raises(ValueError):a.import_payload(payload,'SMH',acquired)
    assert a.revision('US.SMH')==revision and len(a.read('US.SMH')[1])==3


def test_conflicting_overlap_rolls_back_whole_import(tmp_path):
    a=DailyArchive(tmp_path/'daily.db');a.import_payload(response(('06',)),'SMH',ACQUIRED)
    payload=response();payload['bars']['SMH'][0]['close']=102
    with pytest.raises(ValueError,match='冲突'):a.import_payload(payload,'SMH',ACQUIRED)
    assert len(a.read('US.SMH')[1])==1


def test_source_cache_import_refresh_and_ict_exclusion(tmp_path):
    file=tmp_path/'legacy.json';file.write_text('{}',encoding='utf8')
    archive=DailyArchive(tmp_path/'daily.db');now=datetime(2026,7,10,16,5,tzinfo=ET)
    source=HistorySource(file,now,archive)
    loader=MarketLoader(source.fetch)
    try:
        loader.get('US.SMH',('manual',0));loader.jobs.join()
        assert loader.get('US.SMH',0)['terminal_missing']
        archive.import_payload(response(),'SMH',ACQUIRED)
        loader.clear();loader.get('US.SMH',('manual',1));loader.jobs.join()
        d=loader.get('US.SMH',1)
        assert d['daily_only'] and len(d['daily'])==3 and d['minute'].empty
        d['daily'].iloc[0,d['daily'].columns.get_loc('close')]=999
        assert source.fetch('US.SMH')['daily'].close.iloc[0]==101
        o=build_observation('US.SMH',source.fetch('US.SMH'),DEFAULTS,now)
        ranked=prioritize({'US.SMH':o},{},now,symbols=['US.SMH'])
        assert ranked[0]['qualification']==2 and ranked[0]['stage']=='UNKNOWN' and ranked[0]['focus'] is None
        assert not ranked[0]['live_review']
    finally:loader.closed.set()


def test_coverage_only_lists_complete_enabled_daily_data(tmp_path):
    a=DailyArchive(tmp_path/'daily.db');a.import_payload(response(('06',)),'SMH',ACQUIRED)
    entries=[dict(symbol='US.SMH',enabled=True),dict(symbol='US.AAPL',enabled=True)]
    rows=coverage_rows(a,entries,{})
    assert rows[0]['日线观察']=='未合格' and rows[1]['日K']==0


def test_new_daily_chart_defaults_to_daily_and_preserves_plan(tmp_path):
    from streamlit.testing.v1 import AppTest
    file=tmp_path/'legacy.json';file.write_text('{}',encoding='utf8')
    a=DailyArchive(tmp_path/'daily.db');a.import_payload(response(),'SMH',ACQUIRED)
    source=HistorySource(file,datetime(2026,7,10,16,5,tzinfo=ET),a)
    s=Store(tmp_path/'users.db');s.manage_watchlist('add','SMH')
    s.save_plan(dict(symbol='US.SMH',strategy_version='SYNTHETIC_TEST_ONLY',direction='LONG',low=99,high=100,invalid=98,target_low=105,target_high=106,memo='keep'))
    with patch('desk.store.Store',return_value=s),patch('desk.provider.Provider.fetch',lambda self,c:source.fetch(c)):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
        next(x for x in app.selectbox if x.label=='独立窗口观察标的').select('US.SMH').run()
        assert not app.exception
        assert next(r for r in app.radio if r.label=='周期').value=='1D'
        spec=json.loads(next(c.proto.spec for c in app.get('plotly_chart') if c.proto.id.endswith('-mainchart')))
        assert spec['data'][0]['type']=='candlestick' and len(spec['data'][0]['x'])==3
        assert not [t for t in spec['data'] if '历史' in t.get('name','')]
        assert len(s.plans('US.SMH'))==1 and s.plans('US.SMH')[0]['memo']=='keep'
        next(x for x in app.selectbox if x.label=='独立窗口观察标的').select('US.SPY').run()
        next(x for x in app.selectbox if x.label=='独立窗口观察标的').select('US.SMH').run()
        assert not app.exception
        assert next(r for r in app.radio if r.label=='周期').value=='1D'
        assert app.get('plotly_chart')
