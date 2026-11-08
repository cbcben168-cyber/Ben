"""Read-only SQLite snapshots and strict, layered deployment protection.

This is a deployment verifier, never part of the running dashboard. Allowed
observation payloads must be reconstructed from pinned code and saved archives,
not learned from the database being checked.
"""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def digest(value):
    def encode(item):
        if isinstance(item, bytes):
            return {'blob_hex': item.hex()}
        raise TypeError(type(item).__name__)
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, default=encode).encode()).hexdigest()


def snapshot(source, target):
    """SQLite online backup gives one committed snapshot, including WAL content."""
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or target.exists():
        raise ValueError('Snapshot destination must be new and independent')
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as src:
        with closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
    return inspect(target)


def inspect(path):
    """Every table and schema object comes from one explicit read transaction."""
    result = {'tables': {}}
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        result['schema'] = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name").fetchall()
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            quoted = '"'+name.replace('"', '""')+'"'
            columns = [row[1] for row in db.execute('PRAGMA table_info('+quoted+')')]
            rows = db.execute('SELECT * FROM '+quoted).fetchall()
            rows.sort(key=digest)
            result['tables'][name] = dict(columns=columns, rows=rows, sha256=digest([columns, rows]))
    return result


def records(table):
    return [dict(zip(table['columns'], row)) for row in table['rows']]


def compare(before, after, models, window=None, cycles=1):
    """All tables stay exact except append-only, independently verified observations.

    cycles bounds each symbol's loading/loaded transitions for the declared
    server starts. Consecutive duplicate payloads are always rejected.
    """
    errors, additions, checks = [], [], []
    if not isinstance(cycles, int) or isinstance(cycles, bool) or cycles < 1:
        errors.append('invalid declared server-start count')
        cycles = 0
    if before['schema'] != after['schema']:
        errors.append('schema changed')
    if set(before['tables']) != set(after['tables']):
        errors.append('table set changed')
    for name, table in before['tables'].items():
        if name == 'observations':
            continue
        match = name in after['tables'] and table['sha256'] == after['tables'][name]['sha256']
        checks.append(dict(table=name, unchanged=match, rows=len(table['rows']), sha256=table['sha256']))
        if not match:
            errors.append('protected table changed: '+name)
    old = {row['id']: row for row in records(before['tables']['observations'])}
    new = {row['id']: row for row in records(after['tables']['observations'])}
    for identity, row in old.items():
        if new.get(identity) != row:
            errors.append('observation deleted/updated: '+str(identity))
    if before['tables']['observations']['columns'] != after['tables']['observations']['columns']:
        errors.append('observation columns changed')
    last = {row['symbol']: row['signature'] for row in records(before['tables']['observation_snapshots'])}
    counts = {}
    last_at = None
    max_old = max(old, default=0)
    for row in sorted((row for key, row in new.items() if key not in old), key=lambda row: row['id']):
        identity, symbol = row['id'], row['symbol']
        payload_sha = hashlib.sha256(row['payload'].encode()).hexdigest()
        errors_here = []
        if window is None:
            errors_here.append('append requires an explicit observation window')
        try:
            at = datetime.fromisoformat(row['at'])
            if at.tzinfo is None or at.utcoffset() is None:
                raise ValueError('naive time')
            if window and not window[0] <= at <= window[1]:
                errors_here.append('outside declared observation window')
            if last_at is not None and at < last_at:
                errors_here.append('time order reversed')
            last_at = at
        except (ValueError, TypeError):
            errors_here.append('invalid observation timestamp')
        if identity <= max_old:
            errors_here.append('non-append observation id')
        if payload_sha == last.get(symbol):
            errors_here.append('consecutive duplicate observation')
        matched = models.get(symbol, {}).get(payload_sha)
        if matched is None:
            errors_here.append('payload not independently reconstructed')
        key = symbol, matched
        counts[key] = counts.get(key, 0)+1
        if counts[key] > cycles:
            errors_here.append('too many transitions for declared server starts')
        additions.append(dict(id=identity, symbol=symbol, at=row['at'], payload_sha256=payload_sha,
                              state=matched, verified=not errors_here, errors=errors_here))
        errors.extend(f'observation {identity}: {error}' for error in errors_here)
        last[symbol] = payload_sha
    current = {row['symbol']: row['signature'] for row in records(after['tables']['observation_snapshots'])}
    if last != current:
        errors.append('final observation snapshot inconsistent with append sequence')
    return dict(passed=not errors, errors=errors, old_observations=len(old),
                old_rows_preserved=all(new.get(key)==row for key,row in old.items()),
                table_checks=checks, additions=additions)


def compare_experiments(before, after, expected_saves=None, window=None):
    """No store-wide exception: only explicitly declared UI saves may change rows."""
    from dataclasses import asdict
    from desk.experiment import Experiment, VERSION
    expected_saves = expected_saves or {}
    errors = []
    if before['schema'] != after['schema'] or set(before['tables']) != set(after['tables']):
        errors.append('experiment schema changed')
    for name, table in before['tables'].items():
        if name != 'experiments' and after['tables'].get(name, {}).get('sha256') != table['sha256']:
            errors.append('unexpected experiment table change: '+name)
    old = {row['name']: row for row in records(before['tables']['experiments'])}
    new = {row['name']: row for row in records(after['tables']['experiments'])}
    for name in set(old)|set(new)|set(expected_saves):
        if name not in expected_saves:
            if old.get(name) != new.get(name):
                errors.append('unapproved experiment change: '+name)
            continue
        row = new.get(name)
        try:
            assert name.casefold() != 'baseline' and row and 1 <= len(name) <= 60
            assert row['version'] == VERSION
            assert json.loads(row['parameters']) == asdict(Experiment(**expected_saves[name]))
            at = datetime.fromisoformat(row['updated_at'])
            assert at.tzinfo is not None
            if window:
                assert window[0] <= at <= window[1]
        except (AssertionError, ValueError, TypeError, KeyError):
            errors.append('invalid approved experiment save: '+name)
    return dict(passed=not errors, errors=errors, approved_names=sorted(expected_saves))


def reconstruct_models(database, history, archive, updates, evaluated_at):
    """Build exact payload hashes with the unchanged owner and pinned input data."""
    import copy
    import pandas as pd
    from contextlib import contextmanager
    from desk.store import Store
    from desk.plans import active_plan
    from desk.observations import build_observation
    from desk.history_source import HistorySource
    from desk.history_import import DailyArchive
    class ReadOnlyStore(Store):
        def __init__(self, path):
            self.path = str(path)
        @contextmanager
        def connect(self):
            with closing(sqlite3.connect(Path(self.path).resolve().as_uri()+'?mode=ro', uri=True)) as db:
                yield db
    store = ReadOnlyStore(database)
    settings = store.settings()
    source = HistorySource(history, evaluated_at, DailyArchive(archive), DailyArchive(updates))
    models = {}
    for symbol in settings['watchlist']:
        if symbol == 'US.VIX':
            continue
        loaded = source.fetch(symbol)
        # Match the unchanged MarketLoader._work snapshot metadata enrichment.
        for period in ('minute', 'daily'):
            if not loaded[period].empty:
                loaded[period+'_snapshot_at'] = loaded.get(period+'_snapshot_at') or loaded['health'].get('received_at')
        pending = dict(health=dict(quality='UNAVAILABLE'), minute=pd.DataFrame(), daily=pd.DataFrame())
        models[symbol] = {}
        for kind, data in [('loading', pending), ('saved_archive', loaded)]:
            value = build_observation(symbol, copy.deepcopy(data), settings, evaluated_at,
                                      active_plan(store, symbol) or settings['zones'].get(symbol))
            if data.get('daily_only'):
                value.update(source=data['health']['source'], reason='只有供应商日K；未验证分钟完整性及1H ICT资格。')
            evidence = {key: value for key, value in value.items() if key not in {'evaluated_at', 'health'}}
            payload = json.dumps(evidence, sort_keys=True, default=str)
            models[symbol][hashlib.sha256(payload.encode()).hexdigest()] = kind
    return models
