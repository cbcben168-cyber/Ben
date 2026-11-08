import copy
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

import pandas as pd
import pytest

from desk.clock import CAL, ET
from desk.futu_daily import FutuDailyArchive
from desk.futu_daily import CONTRACT
from desk.futu_update import (FutuVersions, TICKERS, archive_identity, payload_identity,
                              publish_capture, run_update, start_update)
from desk.experiment import completed_snapshot, replay_cutoff
from desk.market_state import market_state
from desk.ema_layers import ema_points


def make_payload(ticker, end='2026-02-05', dividend=False):
    dates = [str(t.date()) for t in CAL.sessions_in_range('2026-01-05', end)]
    stamp = datetime.now(timezone.utc).isoformat()
    rows = [dict(code='US.' + ticker, time_key=day + ' 00:00:00', open=100+i,
                 high=102+i, low=99+i, close=101+i, volume=1000+i)
            for i, day in enumerate(dates)]
    qfq = copy.deepcopy(rows)
    actions = []
    if dividend:
        ex_date = '2026-01-20'
        previous = next(r for r in rows if r['time_key'].startswith('2026-01-16'))
        cash = .5
        factor = 1 - cash / previous['close']
        for row in qfq:
            if row['time_key'][:10] < ex_date:
                for field in ('open', 'high', 'low', 'close'):
                    row[field] *= factor
        actions = [dict(ex_div_date=ex_date, per_cash_div=cash,
                        forward_adj_factorA=round(factor, 5), forward_adj_factorB=0)]
    def response(adjustment, records):
        return dict(request=dict(symbol='US.' + ticker, start=dates[0], end=dates[-1],
                                 ktype='K_DAY', session='RTH', autype=adjustment,
                                 requested_at_utc=stamp), acquired_at_utc=stamp,
                    page_complete=True, records=records)
    return dict(format='FUTU_DAILY_V1', provider='FUTU_OPEND', symbol='US.' + ticker,
                sdk_version='synthetic-test',
                valuation_date=pd.Timestamp(stamp).tz_convert(ET).date().isoformat(),
                responses=dict(QFQ=response('QFQ', qfq), NONE=response('NONE', rows)),
                rehab=dict(request=dict(symbol='US.' + ticker, method='get_rehab',
                                        requested_at_utc=stamp), acquired_at_utc=stamp,
                           records=actions))


def capture(directory, payloads):
    directory.mkdir()
    files = {}
    for ticker, payload in zip(TICKERS, payloads):
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
        name = ticker + '.json'
        (directory/name).write_bytes(encoded)
        files[name] = hashlib.sha256(encoded).hexdigest()
    (directory/'manifest.json').write_text(json.dumps(dict(format='FUTU_DAILY_CAPTURE_V1',
                                                           files=files)), encoding='utf-8')
    return directory


@pytest.fixture
def setup(tmp_path):
    baseline = FutuDailyArchive.create(tmp_path/'baseline.sqlite3')
    payloads = [make_payload(ticker) for ticker in TICKERS]
    for payload in payloads:
        baseline.import_payload(payload)
    versions = FutuVersions(baseline.path, tmp_path/'versions')
    return versions, payloads


def test_no_new_day_same_data_keeps_pointer_and_database(setup, tmp_path):
    versions, payloads = setup
    before = versions.baseline.read_bytes()
    result = publish_capture(versions, capture(tmp_path/'capture', payloads), '2026-02-05')
    assert result['status'] == 'UP_TO_DATE' and result['added_days'] == 0
    assert not versions.pointer.exists() and versions.baseline.read_bytes() == before


def test_new_complete_version_and_repeat_are_atomic(setup, tmp_path):
    versions, _ = setup
    payloads = [make_payload(ticker, '2026-02-06') for ticker in TICKERS]
    result = publish_capture(versions, capture(tmp_path/'capture', payloads), '2026-02-06')
    assert result['status'] == 'SUCCESS' and result['added_days'] == 1
    assert versions.summary()['last'] == '2026-02-06'
    assert versions.pointer_data()['previous'] == 'baseline'
    assert archive_identity(versions.current()[0]) == payload_identity(payloads)
    files = list(versions.root.glob('futu_*.sqlite3'))
    repeat = publish_capture(versions, capture(tmp_path/'repeat', payloads), '2026-02-06')
    assert repeat['status'] == 'UP_TO_DATE' and list(versions.root.glob('futu_*.sqlite3')) == files
    assert versions.rollback()['last'] == '2026-02-05'


def test_missing_symbol_or_bar_preserves_old_version(setup, tmp_path):
    versions, _ = setup
    payloads = [make_payload(ticker, '2026-02-06') for ticker in TICKERS]
    capture_dir = capture(tmp_path/'capture', payloads)
    (capture_dir/'XLK.json').unlink()
    with pytest.raises((ValueError, FileNotFoundError)):
        publish_capture(versions, capture_dir, '2026-02-06')
    assert versions.current()[1] == 'baseline'
    payloads[0]['responses']['QFQ']['records'].pop()
    with pytest.raises(ValueError):
        publish_capture(versions, capture(tmp_path/'missing_bar', payloads), '2026-02-06')
    assert versions.current()[1] == 'baseline'


def test_mid_import_failure_leaves_no_partial_publication(setup, tmp_path, monkeypatch):
    versions, _ = setup
    payloads = [make_payload(ticker, '2026-02-06') for ticker in TICKERS]
    capture_dir = capture(tmp_path/'capture', payloads)
    original = FutuDailyArchive.import_payload
    calls = 0
    def fail_second(self, payload):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError('simulated disk failure')
        return original(self, payload)
    monkeypatch.setattr(FutuDailyArchive, 'import_payload', fail_second)
    with pytest.raises(sqlite3.OperationalError):
        publish_capture(versions, capture_dir, '2026-02-06')
    assert versions.current()[1] == 'baseline'
    assert not list(versions.root.glob('stage_*'))
    assert not list(versions.root.glob('futu_*.sqlite3'))


def test_repricing_creates_new_version_without_overwriting_old(setup, tmp_path):
    versions, payloads = setup
    changed = [make_payload(ticker, dividend=ticker == 'SPY') for ticker in TICKERS]
    before = versions.baseline.read_bytes()
    result = publish_capture(versions, capture(tmp_path/'capture', changed), '2026-02-05')
    assert result['status'] == 'SUCCESS' and result['added_days'] == 0
    assert versions.baseline.read_bytes() == before
    assert versions.current()[1] != 'baseline'
    assert FutuDailyArchive(versions.current()[0]).read('US.SPY')[0]['actions']


def test_opend_failure_records_reason_without_publishing(setup, tmp_path, monkeypatch):
    versions, _ = setup
    def fail(*args, **kwargs):
        raise __import__('subprocess').CalledProcessError(1, args[0])
    monkeypatch.setattr('desk.futu_update.subprocess.run', fail)
    result = run_update(versions, tmp_path/'capture_script.py',
                        now=pd.Timestamp('2026-02-09 22:00', tz='UTC'))
    assert result['status'] == 'FAILED' and 'OpenD' in result['reason']
    assert versions.current()[1] == 'baseline'


def test_concurrent_start_uses_one_lock(setup, tmp_path, monkeypatch):
    versions, _ = setup
    calls = []
    class Process:
        pid = 12345
    def spawn(*args, **kwargs):
        calls.append(args)
        return Process()
    monkeypatch.setattr('desk.futu_update.subprocess.Popen', spawn)
    monkeypatch.setattr('desk.futu_update._process_alive', lambda pid: True)
    assert start_update(versions, tmp_path/'update.py')
    assert not start_update(versions, tmp_path/'update.py')
    assert len(calls) == 1


def test_version_switch_refreshes_ema_atr_and_replay_cutoff(tmp_path):
    baseline = FutuDailyArchive.create(tmp_path/'baseline.sqlite3')
    for ticker in TICKERS:
        baseline.import_payload(make_payload(ticker, '2026-04-09'))
    versions = FutuVersions(baseline.path, tmp_path/'versions')
    old_frame = FutuDailyArchive(versions.current()[0]).read('US.SPY')[1]
    old_cutoff = replay_cutoff(pd.Timestamp('2026-04-09').date())
    old_state, _ = market_state(old_frame, '1D', old_cutoff, CONTRACT)
    payloads = [make_payload(ticker, '2026-04-10') for ticker in TICKERS]
    for response in payloads[0]['responses'].values():
        response['records'][-1]['high'] += 3
        response['records'][-1]['low'] -= 2
    assert publish_capture(versions, capture(tmp_path/'capture', payloads), '2026-04-10')['status'] == 'SUCCESS'
    new_frame = FutuDailyArchive(versions.current()[0]).read('US.SPY')[1]
    new_cutoff = replay_cutoff(pd.Timestamp('2026-04-10').date())
    new_state, _ = market_state(new_frame, '1D', new_cutoff, CONTRACT)
    assert versions.summary()['last'] == '2026-04-10'
    assert new_state['ema20'] != old_state['ema20']
    assert new_state['atr14'] != old_state['atr14']
    assert ema_points(new_frame, '1D', new_cutoff, CONTRACT).iloc[-1].short == new_state['ema20']
    snapshot = completed_snapshot(dict(daily=new_frame, minute=pd.DataFrame()), old_cutoff)
    assert snapshot['daily'].ts.max() <= old_cutoff
    assert market_state(snapshot['daily'], '1D', old_cutoff, CONTRACT)[0] == old_state
