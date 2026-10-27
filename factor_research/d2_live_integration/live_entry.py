"""Explicit one-shot real Supervisor. Default is offline; imports never connect."""
from pathlib import Path
import argparse
import importlib.metadata as metadata
import json
import os
import sys
from core import (Clock, Guard, Limits, Stop, digest, encoded, file_sha, require,
                  utc, write_once, directory_bytes, verify_receipts)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXPECTED_ROOT = Path('C:/Users/cbcbe/.codex/worktrees/futu-factor-progress-dashboard-v1/Futu')
RUN = 'D2_SPY_TICKER_ORDER_BOOK_20261027_04'
CUTOFF = '2026-10-27T19:35:00+00:00'
WINDOW = {'launch_start': '2026-10-27T19:34:00+00:00', 'launch_last': '2026-10-27T19:34:20+00:00',
          'start': '2026-10-27T19:35:00+00:00', 'end': '2026-10-27T19:40:00+00:00',
          'cleanup_end': '2026-10-27T19:40:10+00:00'}
POLICY_SHA = 'a84bd8f48d23fcf0d11241a65459a60ed5687fde2cd6d665370e5673971a942d'
CONTRACT = {'schema': 'D2_LIVE_INTEGRATION_V1', 'run_id': RUN,
    'live_default': False, 'symbol': 'US.SPY', 'streams': ['TICKER', 'ORDER_BOOK'],
    'context': 'OpenQuoteContext', 'endpoint': {'host': '127.0.0.1', 'port': 11111},
    'window': WINDOW, 'seal_before': CUTOFF, 'retry': False, 'reschedule': False,
    'policy_sha256': POLICY_SHA, 'budgets': {'sdk_calls': 9, 'call_seconds': 5,
        'observation_seconds': 300, 'lifecycle_seconds': 370, 'records': 50000,
        'queue': 1000, 'disk_bytes': 67108864},
    'resource_risk_accepted': False, 'absolute_utc': 'NOT_VERIFIED',
    'formal_orderflow_research': 'NOT_QUALIFIED', 'edge': 'NOT_TESTED'}


def identity():
    names = ['core.py', 'collector.py', 'sdk_adapter.py', 'process_guard.py',
             'runtime_isolation.py', 'live_entry.py', 'preflight.py', 'read_resource_metadata.ps1',
             'RUNTIME_ISOLATION_POLICY_V3.json', 'protect.py']
    sdk = metadata.distribution('futu-api')
    sdk_root = Path(sdk.locate_file('futu'))
    return {'sources': {n: file_sha(HERE/n) for n in names},
        'tests': {p.name: file_sha(p) for p in sorted((HERE/'tests').glob('*.py'))},
        'python': sys.executable, 'python_sha256': file_sha(sys.executable),
        'sdk_version': sdk.version,
        'sdk_sources': {p.relative_to(sdk_root).as_posix(): file_sha(p)
                        for p in sorted(sdk_root.rglob('*.py'))},
        'packages': {n: metadata.version(n) for n in ('protobuf', 'pandas', 'numpy', 'pytest')},
        'policy_sha256': file_sha(HERE/'POLICY.json')}


def validate_bundle(base, now):
    base = Path(base)
    require(not (base/'TERMINAL.json').exists(), 'RUN_TERMINALLY_BLOCKED')
    require((base/'ONE_SHOT_AUTHORIZATION.json').is_file(), 'LIVE_AUTHORIZATION_REQUIRED')
    auth = json.loads((base/'ONE_SHOT_AUTHORIZATION.json').read_bytes())
    require(auth.get('live_authorized') is True and auth.get('run_id') == RUN and
            auth.get('single_use') is True, 'AUTHORITY_IDENTITY_MISMATCH')
    require(auth.get('risk_acceptance_inherited') is False, 'OLD_RISK_ACCEPTANCE_FORBIDDEN')
    source = (base/'SOURCE_IDENTITY.json').read_bytes()
    require(digest(source) == auth.get('source_sha256') and
            json.loads(source) == identity(), 'SOURCE_IDENTITY_MISMATCH')
    require(file_sha(HERE/'POLICY.json') == POLICY_SHA == auth.get('policy_sha256'), 'POLICY_IDENTITY_MISMATCH')
    contract = (base/'LIVE_CONTRACT.json').read_bytes()
    require(digest(contract) == auth.get('contract_sha256') and json.loads(contract) == CONTRACT,
            'CONTRACT_IDENTITY_MISMATCH')
    require(auth.get('window') == WINDOW, 'WINDOW_IDENTITY_MISMATCH')
    require(utc(auth['sealed_at_utc']) < utc(CUTOFF), 'SEAL_DEADLINE_MISSED')
    require(utc(WINDOW['launch_start']) <= utc(now) <= utc(WINDOW['launch_last']), 'LAUNCH_WINDOW')
    return auth


def validate_safety(state, now):
    from runtime_isolation import state_valid
    require(state.get('window') == WINDOW, 'SAFETY_WINDOW_MISMATCH')
    require(0 <= (utc(now)-utc(state['assessed_at_utc'])).total_seconds() <= 65, 'SAFETY_STALE')
    require(state.get('windows_awake') is True, 'WINDOWS_AWAKE_NOT_PROVEN')
    require(state.get('identity_verified') is True, 'RUNTIME_IDENTITY_NOT_PROVEN')
    require(state_valid(state, False) and state.get('resource_isolation_proven') is True and
            state.get('proceed_allowed') is True, 'RESOURCE_ISOLATION_NOT_PROVEN')


def claim(folder, record):
    try:
        Path(folder).mkdir(exist_ok=False)
    except FileExistsError:
        raise Stop('RUN_ALREADY_EXISTS') from None
    write_once(Path(folder)/'INVOCATION_ONCE.json', encoded(record))


def validate_acceptance(base, auth):
    import xml.etree.ElementTree as ET
    base = Path(base)
    require((base/'ENTRY_ACCEPTANCE.json').is_file(), 'OFFLINE_ACCEPTANCE_REQUIRED')
    acceptance = json.loads((base/'ENTRY_ACCEPTANCE.json').read_bytes())
    require(acceptance.get('status') == 'PASS' and acceptance.get('source_sha256') == auth['source_sha256'] and
            acceptance.get('sealed_at_utc') == auth['sealed_at_utc'] and
            utc(acceptance['sealed_at_utc']) < utc(CUTOFF) and
            file_sha(base/'artifacts/sealed_tests.xml') == acceptance['tests_sha256'], 'OFFLINE_ACCEPTANCE_MISMATCH')
    suites = ET.parse(base/'artifacts/sealed_tests.xml').getroot().findall('testsuite')
    counts = {key: sum(int(s.attrib.get(key, 0)) for s in suites) for key in ('tests','failures','errors','skipped')}
    require(counts['tests'] >= 100 and not any(counts[k] for k in ('failures','errors','skipped')),
            'OFFLINE_TEST_FAILURE')


def validate_worker(folder, config):
    folder = Path(folder).resolve()
    require(folder == HERE/'runs'/RUN and folder.is_dir(), 'LIVE_WORKER_CAPABILITY_REQUIRED')
    require(Path.cwd().resolve() == EXPECTED_ROOT.resolve() == ROOT, 'WRONG_WORKTREE')
    record = json.loads((folder/'INVOCATION_ONCE.json').read_bytes())
    require(os.getppid() == record.get('supervisor_pid'), 'INDEPENDENT_SUPERVISOR_REQUIRED')
    from process_guard import in_job
    require(in_job(), 'OWNED_JOB_REQUIRED')
    auth = validate_bundle(HERE, Clock().stamp()['utc'])
    validate_acceptance(HERE, auth)
    require(record.get('authorization_sha256') == file_sha(HERE/'ONE_SHOT_AUTHORIZATION.json'), 'AUTHORIZATION_CHANGED')
    require(config == json.loads((folder/'CONFIG.json').read_bytes()) and config['window'] == WINDOW,
            'WORKER_CONFIG_CHANGED')
    require(record.get('config_sha256') == digest(encoded(config)), 'CONFIG_IDENTITY_MISMATCH')
    proof = json.loads((HERE/'PREFLIGHT.json').read_bytes())
    require(record.get('safety_sha256') == file_sha(HERE/'PREFLIGHT.json'), 'SAFETY_IDENTITY_MISMATCH')
    validate_safety(proof, Clock().stamp()['utc'])
    return auth


def monitor(job, folder, clock):
    guard = Guard(clock, WINDOW)
    reason = 'CHILD_EXITED'
    while not job.wait(0):
        try:
            stamp = guard.check()
            require((utc(WINDOW['cleanup_end'])-utc(stamp['utc'])).total_seconds() > .2, 'HARD_DEADLINE')
            require(directory_bytes(folder) < Limits().total_bytes, 'RESOURCE_LIMIT')
            path = folder/'CONTROL.jsonl'
            if path.exists():
                raw = path.read_bytes(); require(len(raw) < 65536, 'CONTROL_LIMIT')
                lines = raw.split(b'\n')[:-1]
                data = json.loads(lines[-1]) if lines else {}
                if data.get('in_call'):
                    require((stamp['monotonic_ns']-data['started']['monotonic_ns'])/1e9 < 4.7, 'SDK_TIMEOUT')
        except Exception as exc:
            reason = str(exc) if isinstance(exc, Stop) else 'SUPERVISOR_CONTROL_FAILED'
            job.stop(); break
        clock.sleep(.02)
    return {'reason': reason, 'child_exitcode': job.exitcode(), 'active_owned_processes': job.active_processes(),
            'ended': clock.stamp()}


def finalize(folder, outcome):
    integrity = 'PASS'
    try:
        checked = verify_receipts(folder)
    except Exception:
        checked = {}; integrity = 'PARTIAL'
    path = folder/'COLLECTION_SUMMARY.json'
    summary = json.loads(path.read_bytes()) if path.exists() else None
    complete = bool(summary and summary['status'] == 'COMPLETE' and integrity == 'PASS' and
                    outcome.get('child_exitcode') == 0 and outcome.get('active_owned_processes') == 0)
    result = dict(outcome, status='COMPLETE' if complete else 'PARTIAL', integrity=integrity,
        receipts=checked, collection=summary, mode='REAL_QUOTE_ENGINEERING_OBSERVATION',
        realtime_qualification='NOT_VERIFIED', absolute_utc='NOT_VERIFIED',
        formal_orderflow_research='NOT_QUALIFIED', edge='NOT_TESTED')
    write_once(folder/'END.json', encoded(result))
    files = {p.name: {'bytes': p.stat().st_size, 'sha256': file_sha(p)} for p in folder.iterdir() if p.is_file()}
    blob = encoded({'schema': 'D2_LIVE_MANIFEST_V1', 'files': files, 'status': result['status'], 'self': 'EXCLUDED'})
    require(directory_bytes(folder)+len(blob) <= Limits().total_bytes, 'FINAL_DISK_LIMIT')
    write_once(folder/'MANIFEST.json', blob)
    require(all(file_sha(folder/n) == v['sha256'] for n,v in files.items()), 'MANIFEST_READBACK_FAILED')
    return result


def supervise():
    clock = Clock()
    require(Path.cwd().resolve() == EXPECTED_ROOT.resolve() == ROOT, 'WRONG_WORKTREE')
    auth = validate_bundle(HERE, clock.stamp()['utc'])
    validate_acceptance(HERE, auth)
    proof = json.loads((HERE/'PREFLIGHT.json').read_bytes())
    validate_safety(proof, clock.stamp()['utc'])
    require(file_sha(HERE/'RUNTIME_ISOLATION_SNAPSHOT.json') == proof['snapshot_sha256'], 'SAFETY_SNAPSHOT_CHANGED')
    folder = HERE/'runs'/RUN
    folder.parent.mkdir(exist_ok=True)
    config = {'window': WINDOW, 'run_id': RUN, 'resource_isolation': proof}
    claim(folder, {'supervisor_pid': os.getpid(), 'authorization_sha256': file_sha(HERE/'ONE_SHOT_AUTHORIZATION.json'),
                  'config_sha256': digest(encoded(config)), 'safety_sha256': file_sha(HERE/'PREFLIGHT.json'),
                  'started': clock.stamp()})
    write_once(folder/'CONFIG.json', encoded(config))
    for name in ('LIVE_CONTRACT.json', 'SOURCE_IDENTITY.json', 'ONE_SHOT_AUTHORIZATION.json', 'PREFLIGHT.json', 'ENTRY_ACCEPTANCE.json'):
        write_once(folder/name, (HERE/name).read_bytes())
    from process_guard import Job
    job = None
    outcome = {'reason': 'LAUNCH_FAILED', 'child_exitcode': None, 'active_owned_processes': None}
    try:
        job = Job([sys.executable, '-B', str(HERE/'live_entry.py'), '--worker', str(folder)], ROOT)
        outcome = monitor(job, folder, clock)
    except Exception:
        outcome['reason'] = 'SUPERVISOR_EXCEPTION'
    finally:
        if job is not None:
            try:
                if not job.wait(0): job.stop()
                outcome['active_owned_processes'] = job.active_processes()
                outcome['child_exitcode'] = job.exitcode()
            finally: job.close()
    return finalize(folder, outcome)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--worker')
    args = parser.parse_args(argv)
    try:
        if args.worker:
            folder = Path(args.worker)
            config = json.loads((folder/'CONFIG.json').read_bytes())
            validate_worker(folder, config)
            write_once(folder/'WORKER_ONCE.json', encoded({'pid': os.getpid(), 'started': Clock().stamp()}))
            from collector import collect_live
            result = collect_live(folder, config)
            return 0 if result['status'] == 'COMPLETE' else 2
        if args.live:
            result = supervise()
            print(json.dumps({'status': result['status'], 'reason': result['reason']})); return 0 if result['status'] == 'COMPLETE' else 2
        print('LIVE_DISABLED_BY_DEFAULT; explicit sealed one-shot authorization required')
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc) if isinstance(exc, Stop) else 'ENTRY_FAILED'}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
