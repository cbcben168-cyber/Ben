"""Adversarial checks of the deployment contract, independent of trading logic."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from deployment_protection import snapshot, inspect, compare, compare_experiments
from desk.store import Store
from desk.experiment import BASELINE, ExperimentStore


@pytest.fixture
def case(tmp_path):
    live=tmp_path/'live.sqlite3';store=Store(live)
    store.save('candidate_atr',.20)
    loaded=dict(symbol='US.SPY',status='UNAVAILABLE',mode='PREPARATION',price=None,source='ARCHIVE')
    pending=dict(loaded,source='LOADING')
    store.observation(loaded)
    before=snapshot(live,tmp_path/'before.sqlite3')
    models={'US.SPY':{hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest():kind
                      for kind,value in [('loading',pending),('saved_archive',loaded)]}}
    start=datetime.now(timezone.utc)-timedelta(minutes=1);end=start+timedelta(minutes=2)
    store.observation(pending);store.observation(loaded)
    return dict(path=live,store=store,before=before,models=models,window=(start,end),pending=pending,loaded=loaded)


def verify(case,**options):
    return compare(case['before'],inspect(case['path']),case['models'],window=case['window'],**options)


def test_verified_loading_transitions_allow_old_payload_reappearance(case):
    result=verify(case)
    assert result['passed'] and result['old_rows_preserved'] and len(result['additions'])==2
    assert [row['state'] for row in result['additions']]==['loading','saved_archive']
    assert all(row['unchanged'] for row in result['table_checks'])
    # Existing owner de-duplicates the immediate snapshot, not all-time payloads.
    case['store'].observation(case['loaded'])
    assert len(verify(case)['additions'])==2


@pytest.mark.parametrize('mutation',[
    "DELETE FROM observations WHERE id=1",
    "UPDATE observations SET payload='{}' WHERE id=1",
    "UPDATE observations SET at='2099-01-01T00:00:00Z' WHERE id=2",
    "UPDATE observations SET payload='{}' WHERE id=2",
    "INSERT INTO observations(at,symbol,payload) SELECT at,symbol,payload FROM observations WHERE id=3",
    "UPDATE settings SET value='0.99' WHERE key='candidate_atr'",
    "INSERT INTO notes VALUES('US.SPY','changed','2026-11-08')",
    "INSERT INTO events(at,kind,symbol,reason) VALUES('2026-11-08','SYSTEM_HEALTH','US.SPY','changed')",
    "UPDATE observation_snapshots SET signature='forged'",
    "INSERT INTO observation_states VALUES('LIVE','US.SPY','ICT','RTH','QUALIFIED','2026-11-08T00:00:00Z')",
    "ALTER TABLE observations ADD COLUMN forged TEXT",
    "CREATE TABLE unexpected(secret TEXT)",
])
def test_abnormal_writes_are_rejected_without_any_ignored_table(case,mutation):
    with sqlite3.connect(case['path']) as db:db.execute(mutation)
    assert not verify(case)['passed']


@pytest.mark.parametrize('key,value',[('source','FAKE_SOURCE'),('mode','LIVE'),('status','AVAILABLE'),('reference_at','2099-01-01T00:00:00Z'),('ict_live_qualification',True)])
def test_forged_source_future_evidence_and_qualification_are_rejected(case,key,value):
    payload=dict(case['loaded'],**{key:value})
    case['store'].observation(payload)
    assert not verify(case)['passed']


def test_unbounded_or_undeclared_extra_cycles_are_rejected(case):
    case['store'].observation(case['pending']);case['store'].observation(case['loaded'])
    assert not verify(case)['passed']
    assert verify(case,cycles=2)['passed']
    assert not compare(case['before'],inspect(case['path']),case['models'],cycles=2)['passed']


def test_experiments_only_allow_explicit_verified_saves(tmp_path):
    path=tmp_path/'experiments.sqlite3';store=ExperimentStore(path)
    store.save('original',BASELINE)
    before=snapshot(path,tmp_path/'experiments-before.sqlite3')
    config=replace(BASELINE,ema_short=5)
    store.save('approved',config)
    current=inspect(path)
    assert not compare_experiments(before,current)['passed']
    window=(datetime.now(timezone.utc)-timedelta(minutes=1),datetime.now(timezone.utc)+timedelta(minutes=1))
    assert compare_experiments(before,current,{'approved':asdict(config)},window)['passed']
    store.save('original',config)
    assert not compare_experiments(before,inspect(path),{'approved':asdict(config)},window)['passed']
    with sqlite3.connect(path) as db:db.execute("DELETE FROM experiments WHERE name='original'")
    assert not compare_experiments(before,inspect(path),{'approved':asdict(config)},window)['passed']


def test_snapshot_is_stable_includes_wal_and_never_overwrites(tmp_path):
    path=tmp_path/'wal.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE item(id INTEGER)')
        db.execute('INSERT INTO item VALUES(1)');db.commit()
        saved=snapshot(path,tmp_path/'saved.sqlite3')
        db.execute('INSERT INTO item VALUES(2)');db.commit()
        assert len(saved['tables']['item']['rows'])==1
        assert len(inspect(tmp_path/'saved.sqlite3')['tables']['item']['rows'])==1
        assert len(inspect(path)['tables']['item']['rows'])==2
        with pytest.raises(ValueError):snapshot(path,tmp_path/'saved.sqlite3')
