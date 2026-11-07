"""Read-only fingerprints and isolated copies for the v0.4.4 acceptance run."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
from contextlib import closing

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT/'data/v044/protection.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def user_state(database):
    result = {}
    with closing(sqlite3.connect(Path(database).as_uri()+'?mode=ro', uri=True)) as connection:
        tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for name in sorted(tables & {'plan_versions', 'plans', 'settings', 'notes', 'trades', 'trade_records'}):
            rows = sorted(connection.execute('SELECT * FROM "'+name+'"').fetchall(), key=str)
            result[name] = dict(rows=len(rows), sha256=hashlib.sha256(json.dumps(rows, ensure_ascii=False, default=str).encode()).hexdigest())
        result['integrity'] = connection.execute('PRAGMA integrity_check').fetchone()[0]
    return result


def stage(source, frozen):
    paths = [source/'data/v04/history.json', source/'data/v042/history.sqlite3',
             source/'data/v043/updates.sqlite3', source/'data/v043/latest.json']
    # All runtime Python files except the three explicitly modified integration files.
    paths += [p for p in (source/'desk').glob('*.py') if p.name not in {'decision_home.py', 'market_state.py'}]
    paths += list((frozen/'desk').glob('*.py')) + [frozen/'app.py', frozen/'data/desk.sqlite3']
    manifest = dict(files={str(p): digest(p) for p in paths if p.exists()},
                    database=str(source/'data/v04/desk.sqlite3'),
                    user_state=user_state(source/'data/v04/desk.sqlite3'))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    for relative in ('data/v04/history.json', 'data/v042/history.sqlite3',
                     'data/v043/updates.sqlite3', 'data/v043/latest.json'):
        target = ROOT/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source/relative, target)
    # SQLite online backup opens the source read-only and copies a consistent snapshot.
    with closing(sqlite3.connect((source/'data/v04/desk.sqlite3').as_uri()+'?mode=ro', uri=True)) as original:
        with closing(sqlite3.connect(ROOT/'data/v044/preview.sqlite3')) as target:
            original.backup(target)
    return dict(protected_files=len(manifest['files']), user_state=manifest['user_state'])


def verify():
    manifest = json.loads(REPORT.read_text(encoding='utf-8'))
    changed = [p for p, before in manifest['files'].items() if digest(p) != before]
    current = user_state(manifest['database'])
    return dict(protected_files_unchanged=not changed, changed=changed,
                user_state_unchanged=current == manifest['user_state'], current=current)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path)
    parser.add_argument('--frozen', type=Path)
    args = parser.parse_args()
    print(json.dumps(stage(args.source, args.frozen) if args.source else verify(), indent=2))
