import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'bb098c7fa0b5f88299df2f154a30edb2e80a6e0b25e0331cb61c7c9b4e8778e6'
NOW = datetime(2026, 11, 13, 21, 0, 30, tzinfo=timezone.utc)
MS = lambda iso: int(datetime.fromisoformat(iso).timestamp()*1000)


def request(**changes):
    p = dict(schema='V23C_SIGNAL_V1', strategy='QQQ_V23C_P0_AB', source_sha256=SHA,
             configuration_id='P0_DEFAULT', model_mode=0, symbol='NASDAQ:QQQ',
             timeframe='1D', session='RTH', event='REQUEST', action='REDUCE',
             bar_open_ms=MS('2026-11-13T14:30:00+00:00'), bar_close_ms=MS('2026-11-13T21:00:00+00:00'),
             emitted_ms=MS('2026-11-13T21:00:01+00:00'), confirmed=True, realtime=True,
             close=100., target_exposure_pct=100., model_exposure_pct=135.,
             model_position_qty=1350., model_delta_qty=-350., market_level=2,
             boost_score=4, data_ready=True, external_finality='UNVERIFIED')
    return dict(p, **changes)


def fill(**changes):
    return dict(dict(schema='V23C_FILL_V1', strategy='QQQ_V23C_P0_AB', source_sha256=SHA,
        configuration_id='P0_DEFAULT', model_mode=0, symbol='NASDAQ:QQQ', timeframe='1D', session='RTH',
        event='MODEL_FILL', bar_open='2026-11-16T14:30:00Z', filled_at='2026-11-16T14:30:01Z',
        order_id='Rebalance Reduce', order_comment='Reduce', model_order_action='sell',
        model_fill_qty=350., model_fill_price=99., model_position_after=1000.), **changes)


@pytest.fixture
def store(tmp_path):
    from desk.v23c_signals import SignalStore
    return SignalStore(tmp_path/'signals.sqlite3')


def test_cli_check_is_read_only_and_loopback_only(tmp_path):
    db = tmp_path/'signals.sqlite3'
    r = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(ROOT/'scripts/run_v23c_receiver.py'),
                        '--check', '--db', str(db)], capture_output=True, text=True, encoding='utf-8')
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)['loopback_only'] is True
    assert not db.exists()


def test_request_and_simulated_fill_are_separate_and_never_account_trades(store):
    a = store.ingest(request(), NOW)
    b = store.ingest(fill(), datetime(2026,11,16,14,30,10,tzinfo=timezone.utc))
    assert a['event']=='REQUEST' and a['action']=='REDUCE' and a['quality']=='FRESH'
    assert b['event']=='MODEL_FILL' and b['quality']=='FRESH'
    assert not a['trading_eligible'] and not b['trading_eligible']
    assert len(store.read()) == 2
    assert store.latest_request()['id'] == a['id']


def test_duplicate_is_idempotent_conflicting_same_bar_rejected(store):
    a=store.ingest(request(), NOW)
    b=store.ingest(request(), NOW+timedelta(seconds=1))
    assert b['duplicate'] and b['id']==a['id'] and len(store.read())==1
    with pytest.raises(ValueError, match='CONFLICT'):
        store.ingest(request(target_exposure_pct=80.), NOW)
    assert store.read()[0]['payload']['target_exposure_pct']==100.


def test_old_delivery_and_late_history_cannot_replace_current_request(store):
    current=store.ingest(request(), NOW)
    old=request(bar_open_ms=MS('2026-11-12T14:30:00+00:00'),bar_close_ms=MS('2026-11-12T21:00:00+00:00'),
                emitted_ms=MS('2026-11-12T21:00:01+00:00'))
    assert store.ingest(old, NOW)['quality']=='STALE'
    assert store.latest_request()['id']==current['id']
    assert store.ingest(request(configuration_id='delayed'), NOW+timedelta(minutes=6))['quality']=='STALE'


@pytest.mark.parametrize('changes,code', [
    ({'symbol':'AMEX:SPY'},'SYMBOL'), ({'timeframe':'60'},'TIMEFRAME'),
    ({'session':'EXTENDED'},'SESSION'), ({'confirmed':False},'UNCONFIRMED'),
    ({'realtime':False},'HISTORICAL'), ({'source_sha256':'0'*64},'VERSION'),
    ({'target_exposure_pct':136.},'NUMBER'), ({'close':float('nan')},'NUMBER'),
    ({'model_delta_qty':float('inf')},'NUMBER'), ({'model_mode':True},'MODE'),
    ({'emitted_ms':MS('2026-11-13T21:01:00+00:00')},'FUTURE'),
    ({'bar_close_ms':MS('2026-11-13T20:00:00+00:00')},'BOUNDARY'),
    ({'action':'INCREASE'},'DIRECTION'), ({'configuration_id':'<script>x</script>'},'CONFIGURATION'),
])
def test_bad_inputs_are_rejected_without_rows(store, changes, code):
    with pytest.raises(ValueError,match=code): store.ingest(request(**changes),NOW)
    assert store.read()==[]


def test_missing_dependencies_and_state_heartbeat_do_not_become_trade_permission(store):
    row=store.ingest(request(data_ready=False),NOW)
    assert row['quality']=='DATA_GAP' and not row['trading_eligible']
    heartbeat=request(configuration_id='hold',event='STATE',action='HOLD',
                      model_delta_qty=0.,model_exposure_pct=100.)
    assert store.ingest(heartbeat,NOW)['event']=='STATE'
    assert len(store.read())==2


def test_early_close_and_dst_use_exchange_calendar(store):
    early=request(bar_open_ms=MS('2026-11-27T14:30:00+00:00'),bar_close_ms=MS('2026-11-27T18:00:00+00:00'),
                  emitted_ms=MS('2026-11-27T18:00:01+00:00'))
    assert store.ingest(early,datetime(2026,11,27,18,0,2,tzinfo=timezone.utc))['quality']=='FRESH'
    summer=request(bar_open_ms=MS('2026-10-30T13:30:00+00:00'),bar_close_ms=MS('2026-10-30T20:00:00+00:00'),
                   emitted_ms=MS('2026-10-30T20:00:01+00:00'))
    assert store.ingest(summer,datetime(2026,10,30,20,0,2,tzinfo=timezone.utc))['quality']=='FRESH'


def test_fill_at_open_is_not_claimed_to_be_a_confirmed_close(store):
    now=datetime(2026,11,16,14,30,10,tzinfo=timezone.utc)
    row=store.ingest(fill(),now)
    assert row['event']=='MODEL_FILL' and 'target_exposure_pct' not in row['payload']
    assert store.latest_request() is None
    with pytest.raises(ValueError,match='FILL_TIME'):
        store.ingest(fill(filled_at='2026-11-16T13:30:01Z'),now)


def test_unknown_fields_and_secrets_cannot_be_stored(store):
    with pytest.raises(ValueError,match='FIELDS'):
        store.ingest(dict(request(),secret='test-only-private-value'),NOW)
    assert store.read()==[]


def test_foreign_database_cannot_be_initialized_or_modified(tmp_path):
    from desk.v23c_signals import SignalStore
    path=tmp_path/'user.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE plans(value TEXT)');db.execute("INSERT INTO plans VALUES('preserve')")
    before=path.read_bytes()
    with pytest.raises(ValueError,match='FOREIGN_DATABASE'): SignalStore(path)
    assert path.read_bytes()==before


def test_simulation_is_an_out_of_band_receiver_label(store):
    row=store.ingest(request(),NOW,simulation=True)
    assert row['simulation'] and row['quality']=='SIMULATION'
    assert not row['trading_eligible']
