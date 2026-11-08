"""Audit consistent copies from the v0.4.4.1 rollback; never opens production."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from deployment_protection import inspect, compare, reconstruct_models, records
from desk.clock import ET


def audit(folder, history_root, start, end):
    before = inspect(folder/'before.sqlite3')
    current = inspect(folder/'current.sqlite3')
    models = reconstruct_models(folder/'before.sqlite3', history_root/'data/v04/history.json',
                                history_root/'data/v042/history.sqlite3', history_root/'data/v043/updates.sqlite3',
                                datetime(2026,10,29,16,2,tzinfo=ET))
    result = compare(before, current, models, window=(start,end), cycles=2)
    old = records(before['tables']['observations'])
    rows = {row['id']: row for row in records(current['tables']['observations'])}
    previous = {row['payload'] for row in old}
    state = {row['symbol']: row['signature'] for row in records(before['tables']['observation_snapshots'])}
    for item in result['additions']:
        row = rows[item['id']]
        payload = json.loads(row['payload'])
        item.update(version='v0.4.4.1' if row['id'] <=222 else 'restored_v0.4.4',
                    prior_payload_seen=row['payload'] in previous,
                    same_as_previous_symbol_snapshot=state.get(row['symbol'])==item['payload_sha256'],
                    status=payload['status'],mode=payload['mode'],source=payload['source'],
                    reference_price=payload['reference_price'],candidates=len(payload['candidates']),
                    monitors=len(payload['monitors']),history_snapshots=payload['history_snapshots'])
        previous.add(row['payload']);state[row['symbol']]=item['payload_sha256']
    result['snapshot_sha256']={name:hashlib.sha256((folder/(name+'.sqlite3')).read_bytes()).hexdigest() for name in ('before','current')}
    result['conclusion'] = 'VERIFIED_APPEND_ONLY' if result['passed'] else 'BLOCKED'
    result['limits'] = [
        'Endpoint comparison proves original rows remain identical; it cannot establish that no transient SQL UPDATE/DELETE was ever issued without a historical SQL trace.',
        'Loading payloads retain the existing Futu template but have no price, candidates or validated levels; they are not Futu market-data evidence.',
        'Acquisition timestamps in daily archive metadata follow the fixed analysis date; they are before the wall-clock record time, and no price or trading qualification is derived from them.'
    ]
    (folder/'root-cause-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--history-root',type=Path,required=True)
    parser.add_argument('--start',type=datetime.fromisoformat,required=True)
    parser.add_argument('--end',type=datetime.fromisoformat,required=True)
    args=parser.parse_args()
    result=audit(args.folder,args.history_root,args.start,args.end)
    print(json.dumps({key:result[key] for key in ('passed','errors','old_observations','old_rows_preserved','conclusion')},ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
