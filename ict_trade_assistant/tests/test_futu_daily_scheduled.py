from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import pytest

from scripts import futu_daily_runtime as runtime
from scripts import run_futu_daily_scheduled as scheduled
from scripts import start_ict_8506_v045 as launcher
from desk.futu_update import FutuVersions, _atomic_json, read_json
from desk.futu_task import task_guard, bounded_worker
from test_futu_update_v045 import setup, capture, make_payload, TICKERS

NOW = datetime.fromisoformat('2026-02-06T06:30:00+00:00')
NEXT = datetime.fromisoformat('2026-02-07T06:30:00+00:00')
SOURCE = Path(__file__).resolve().parents[1]


@pytest.fixture
def profile(setup, tmp_path, monkeypatch):
    old, _ = setup
    root = tmp_path / 'app'
    data = root / 'data'
    data.mkdir(parents=True)
    baseline = data / 'baseline.sqlite3'
    baseline.write_bytes(old.baseline.read_bytes())
    versions = data / 'versions'
    versions.mkdir()
    env = {k: None for k in runtime.ENV_KEYS}
    for key in ('ICT_V04_DB', 'ICT_V04_HISTORY', 'ICT_EXPERIMENT_DB'):
        p = data / (key + '.fixture')
        p.write_bytes(b'protected input')
        env[key] = str(p)
    env.update(ICT_FUTU_DAILY_ARCHIVE=str(baseline), ICT_FUTU_DAILY_ROOT=str(versions))
    for name in runtime.ENGINE_FILES | {'scripts/run_server.py'}:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('# isolated accepted fixture: ' + name, encoding='utf-8')
    sources = [root / 'app.py', root / 'scripts/run_server.py', *sorted((root / 'desk').glob('*.py'))]
    value = dict(schema='ICT_FUTU_DAILY_RUNTIME_V1', app_root=str(root), python=sys.executable,
                 environment=env, baseline_sha256=runtime.sha256(baseline),
                 engine_sha256={n: runtime.sha256(root / n) for n in runtime.ENGINE_FILES},
                 build_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest(),
                 unattended_enabled=True, real_new_day_accepted=True, vendor_finality_accepted=True)
    path = tmp_path / 'profile.json'
    path.write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(runtime, 'ROOT', root)
    return value, path, FutuVersions(baseline, versions)


@pytest.mark.parametrize('stamp,target', [
    ('2026-11-10T06:30:00+00:00', '2026-11-09'),
    ('2026-07-14T06:30:00+00:00', '2026-07-13'),
    ('2026-03-09T06:30:00+00:00', '2026-03-06'),
    ('2026-11-02T06:30:00+00:00', '2026-10-30'),
    ('2026-11-27T06:30:00+00:00', '2026-11-25'),
    ('2026-11-28T06:30:00+00:00', '2026-11-27'),
    ('2026-11-10T06:29:59+00:00', None),
    ('2026-11-10T14:00:00+00:00', None),
    ('2026-07-14T13:00:00+00:00', None),
    ('2026-11-09T21:02:00+00:00', None),
])
def test_safe_target_dst_holidays_early_close_and_late_catchup(stamp, target):
    assert scheduled.eligible_target(datetime.fromisoformat(stamp)) == target


def test_naive_scheduler_clock_is_rejected():
    with pytest.raises(ValueError): scheduled.eligible_target(datetime(2026, 11, 10, 6, 30))


def test_profile_and_clean_environment_preserve_exact_paths(profile):
    config, path, _ = profile
    assert runtime.load_config(path) == config
    env = runtime.launch_environment(config, {'PATH': 'retained', 'ICT_DAILY_ARCHIVE': 'wrong',
                                              'ICT_LIVE_OVERRIDE': 'unapproved'})
    assert env['PATH'] == 'retained'
    assert {k: env.get(k) for k in runtime.ENV_KEYS} == config['environment']
    assert 'ICT_DAILY_ARCHIVE' not in env and 'ICT_LIVE_OVERRIDE' not in env


@pytest.mark.parametrize('mutation', ['root', 'baseline', 'engine', 'protected', 'escape', 'overlap', 'switch', 'alias'])
def test_configuration_drift_fails_closed(profile, mutation, tmp_path):
    config, path, versions = profile
    if mutation == 'root': config['app_root'] = str(tmp_path)
    if mutation == 'baseline': versions.baseline.write_bytes(b'changed')
    if mutation == 'engine': (runtime.ROOT / 'desk/futu_update.py').write_text('changed')
    if mutation == 'protected': Path(config['environment']['ICT_V04_DB']).unlink()
    if mutation == 'escape': config['environment']['ICT_V04_DB'] = str(tmp_path)
    if mutation == 'overlap': config['environment']['ICT_FUTU_DAILY_ROOT'] = str(runtime.ROOT / 'data')
    if mutation == 'switch': config['unattended_enabled'] = 'true'
    if mutation == 'alias': config['environment']['ICT_EXPERIMENT_DB'] = config['environment']['ICT_V04_DB']
    path.write_text(json.dumps(config))
    with pytest.raises((ValueError, OSError)):
        runtime.load_config(path)


@pytest.mark.parametrize('key', ['unattended_enabled', 'real_new_day_accepted', 'vendor_finality_accepted'])
def test_unaccepted_or_disabled_run_has_no_side_effects(profile, key):
    config, _, versions = profile
    config[key] = False
    with pytest.raises(ValueError): scheduled.run_cycle(config, now=NEXT)
    assert list(versions.root.iterdir()) == []


def test_nontrading_and_already_updated_days_make_no_request_or_version(profile):
    config, _, versions = profile
    def forbidden(*args): raise AssertionError('must not contact OpenD')
    assert scheduled.run_cycle(config, now=NOW, login=forbidden)['status'] == 'SKIPPED'
    assert list(versions.root.iterdir()) == []
    assert scheduled.run_cycle(config, now=datetime.fromisoformat('2026-02-06T21:02:00+00:00'),
                               login=forbidden)['status'] == 'DEFERRED'


def test_login_failure_and_validation_failure_are_terminal_across_restarts(profile):
    config, _, versions = profile
    result = scheduled.run_cycle(config, now=NEXT, login=lambda *a: False)
    assert result['status'] == 'FAILED' and result['attempt'] == 1
    assert result['phase'] == 'quote_login' and result['exit_code'] == 1
    assert result['elapsed_seconds'] >= 0 and result['started_at'] <= result['finished_at']
    assert not versions.pointer.exists()
    result = scheduled.run_cycle(config, now=NEXT, login=lambda *a: pytest.fail('no retry after login failure'))
    assert 'terminal' in result['reason']
    assert read_json(versions.root / 'scheduler/day_2026-02-06.json')['attempts'] == 1


def test_busy_or_transient_timeout_has_only_two_durable_attempts(profile):
    config, _, versions = profile
    calls, waits = [], []
    def busy(*args):
        calls.append(True)
        return dict(status='BUSY', reason='web owns lock')
    result = scheduled.run_cycle(config, now=NEXT, login=lambda *a: True, update=busy, sleep=waits.append)
    assert result['status'] == 'FAILED' and len(calls) == 2 and waits == [60]
    assert scheduled.run_cycle(config, now=NEXT, login=lambda *a: pytest.fail())['status'] == 'FAILED'
    assert read_json(versions.root / 'scheduler/day_2026-02-06.json')['attempts'] == 2
    assert scheduled.retryable(dict(status='FAILED', reason='Futu OpenD响应超时，请检查连接后重试。'))
    assert not scheduled.retryable(dict(status='FAILED', reason='unclassified capture exit'))


def test_supplier_validation_failure_is_not_retried(profile):
    config, _, versions = profile
    calls = []
    def failed(*args):
        calls.append(True)
        return dict(status='FAILED', target='2026-02-06', phase='校验', reason='QFQ mismatch')
    result = scheduled.run_cycle(config, now=NEXT, login=lambda *a: True, update=failed,
                                 sleep=lambda _: pytest.fail('must not retry validation'))
    assert result['phase'] == '校验' and result['exit_code'] == 1 and len(calls) == 1
    assert not versions.pointer.exists()


def test_crash_reservation_is_not_reset_and_corrupt_ledger_is_not_overwritten(profile):
    config, _, versions = profile
    directory = versions.root / 'scheduler'
    directory.mkdir()
    state = directory / 'day_2026-02-06.json'
    _atomic_json(state, dict(target='2026-02-06', attempts=1, status='RUNNING'))
    calls = []
    def failed(*args):
        calls.append(True)
        return dict(status='FAILED', reason='validation')
    assert scheduled.run_cycle(config, now=NEXT, login=lambda *a: True, update=failed)['attempt'] == 2
    assert len(calls) == 1
    state.write_text('{broken')
    with pytest.raises(ValueError): scheduled.run_cycle(config, now=NEXT)
    assert state.read_text() == '{broken'


def test_real_engine_guard_blocks_web_concurrency_without_clearing_owner(profile):
    config, _, versions = profile
    _atomic_json(versions.lock, dict(token='web-owner', created=time.time()))
    with task_guard(versions.root) as owned:
        assert owned
        result = scheduled.update_once(config, versions, '2026-02-06')
        assert result['status'] == 'BUSY'
        assert read_json(versions.lock)['token'] == 'web-owner'


def test_success_uses_existing_publication_and_preserves_all_inputs(profile, tmp_path):
    from desk.futu_update import publish_capture
    config, _, versions = profile
    protected = {p: p.read_bytes() for p in [versions.baseline, *[
        Path(config['environment'][k]) for k in ('ICT_V04_DB', 'ICT_V04_HISTORY', 'ICT_EXPERIMENT_DB')]]}
    packets = capture(tmp_path / 'captured', [make_payload(t, '2026-02-06') for t in TICKERS])
    def publish(config, archive, target):
        return publish_capture(archive, packets, target, token='isolated-synthetic')
    result = scheduled.run_cycle(config, now=NEXT, login=lambda *a: True, update=publish)
    assert result['status'] == 'SUCCESS' and result['added_days'] == 1
    assert result['before'] == 'baseline' and result['after'] != 'baseline'
    assert versions.summary()['last'] == '2026-02-06'
    assert all(p.read_bytes() == data for p, data in protected.items())
    assert scheduled.run_cycle(config, now=NEXT, login=lambda *a: pytest.fail())['status'] == 'SKIPPED'
    assert len(list(versions.root.glob('futu_*.sqlite3'))) == 1


def test_result_correlation_ignores_previous_receipt_and_recovers_pointer(profile, monkeypatch):
    config, _, versions = profile
    token = 'a' * 32
    _atomic_json(versions.status, dict(status='SUCCESS', token='old'))
    _atomic_json(versions.root / 'result_old.json', dict(status='SUCCESS', token='old'))
    def started(*args, **kwargs):
        _atomic_json(versions.lock, dict(token=token, created=time.time()))
        return True
    monkeypatch.setattr(scheduled, 'start_update', started)
    ticks = iter([0, 0, 651])
    assert scheduled.update_once(config, versions, '2026-02-05', clock=lambda: next(ticks),
                                  sleep=lambda _: None)['status'] == 'FAILED'
    _atomic_json(versions.pointer, dict(current='baseline', previous=None,
                 result=dict(status='SUCCESS', token=token)))
    assert scheduled.update_once(config, versions, '2026-02-05')['status'] == 'SUCCESS'
    assert scheduled.update_once(config, versions, '2026-02-06')['status'] == 'FAILED'


def test_validation_default_and_launcher_do_not_start_a_process(profile, monkeypatch):
    _, path, versions = profile
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('unexpected process'))
    assert scheduled.main(['--config', str(path)]) == 0
    assert launcher.main(['--config', str(path)]) == 0
    assert list(versions.root.iterdir()) == []


def test_disabled_run_refuses_before_any_directory_or_sdk_work(profile):
    config, path, versions = profile
    config['unattended_enabled'] = False
    path.write_text(json.dumps(config))
    assert scheduled.main(['--config', str(path), '--run']) == 1
    assert list(versions.root.iterdir()) == []


def test_whole_cycle_has_fixed_deadline_and_records_timeout(profile, monkeypatch):
    config, path, versions = profile
    # main intentionally applies environment only in its own CLI process.
    monkeypatch.setattr(scheduled, 'launch_environment', lambda config: dict(os.environ))
    calls = []
    def timeout(command, seconds, log):
        calls.append((command, seconds))
        raise subprocess.TimeoutExpired(command, seconds)
    monkeypatch.setattr(scheduled, 'bounded_worker', timeout)
    assert scheduled.main(['--config', str(path), '--run']) == 1
    assert calls[0][1] == 1500
    assert calls[0][0][-1] == '--worker'
    failures = list((versions.root / 'scheduler').glob('failure_*.json'))
    assert len(failures) == 1 and read_json(failures[0])['status'] == 'FAILED'
    assert not versions.pointer.exists()


def test_launcher_restores_profile_in_child_without_opening_production(profile, monkeypatch):
    config, path, _ = profile
    monkeypatch.setattr(launcher, 'ROOT', runtime.ROOT)
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address): assert address == ('127.0.0.1', 8506)
    monkeypatch.setattr(launcher.socket, 'socket', Probe)
    calls = []
    def spawn(command, **kwargs):
        calls.append((command, kwargs))
        return type('Process', (), {'pid': 123})()
    monkeypatch.setattr(launcher.subprocess, 'Popen', spawn)
    monkeypatch.setenv('ICT_FUTU_DAILY_ROOT', 'wrong-parent-value')
    assert launcher.main(['--config', str(path), '--start']) == 0
    command, options = calls[0]
    assert command[-3:] == ['--history', '--port', '8506']
    assert options['cwd'] == runtime.ROOT
    assert {k: options['env'].get(k) for k in runtime.ENV_KEYS} == config['environment']
    assert os.environ['ICT_FUTU_DAILY_ROOT'] == 'wrong-parent-value'


def test_real_child_receives_recovered_environment_with_no_web_service(profile, monkeypatch):
    config, path, _ = profile
    monkeypatch.setattr(launcher, 'ROOT', runtime.ROOT)
    entry = runtime.ROOT / 'scripts/run_server.py'
    entry.write_text('import os,json; print(json.dumps({k:v for k,v in os.environ.items() if k.startswith("ICT_")}))')
    sources = [runtime.ROOT / 'app.py', entry, *sorted((runtime.ROOT / 'desk').glob('*.py'))]
    config['build_sha256'] = hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest()
    path.write_text(json.dumps(config))
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address): pass
    monkeypatch.setattr(launcher.socket, 'socket', Probe)
    monkeypatch.setenv('ICT_FUTU_DAILY_ROOT', 'wrong inherited path')
    assert launcher.main(['--config', str(path), '--start']) == 0
    output = runtime.ROOT / 'data/v045-launch-out.log'
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if output.exists() and output.read_text().strip(): break
        time.sleep(.05)
    child = json.loads(output.read_text())
    assert child == {k:v for k,v in config['environment'].items() if v is not None}


def test_occupied_port_refuses_launch_and_does_not_stop_any_process(profile, monkeypatch):
    _, path, _ = profile
    class Probe:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address): raise OSError('occupied')
    monkeypatch.setattr(launcher.socket, 'socket', Probe)
    monkeypatch.setattr(subprocess, 'Popen', lambda *a, **k: pytest.fail('must refuse occupied port'))
    assert launcher.main(['--config', str(path), '--start']) == 1


@pytest.mark.parametrize('logged_in,ret,expected', [(True, 0, True), (False, 0, False), (True, -1, False)])
def test_quote_only_login_gate_does_not_require_trading_login(monkeypatch, logged_in, ret, expected):
    import types
    closed = []
    class Quote:
        def __init__(self, **kwargs): assert kwargs == dict(host='127.0.0.1', port=11111)
        def get_global_state(self): return ret, dict(qot_logined=logged_in, trd_logined=False)
        def close(self): closed.append(True)
    stub = types.SimpleNamespace(OpenQuoteContext=Quote, RET_OK=0,
        SysConfig=types.SimpleNamespace(set_all_thread_daemon=lambda _: None, enable_console_log=lambda _: None))
    monkeypatch.setitem(sys.modules, 'futu', stub)
    assert runtime.check_opend() is expected
    assert closed == [True]


def test_task_template_is_disabled_bounded_and_does_not_reuse_ict_tasks():
    tree = ET.parse(SOURCE / 'ops/ICT_FUTU_DAILY_8506_V045.xml')
    ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    def text(path): return tree.find(path, ns).text
    assert text('t:Settings/t:Enabled') == 'false'
    assert text('t:Settings/t:MultipleInstancesPolicy') == 'IgnoreNew'
    assert text('t:Settings/t:ExecutionTimeLimit') == 'PT27M'
    assert text('t:Triggers/t:CalendarTrigger/t:StartBoundary').endswith('06:30:00Z')
    assert text('t:Principals/t:Principal/t:LogonType') == 'InteractiveToken'
    assert 'RTH_ACCEPTANCE' not in ET.tostring(tree.getroot(), encoding='unicode')


def test_outer_job_closes_nested_owned_tree_and_releases_lock(tmp_path):
    marker = tmp_path / 'owner.ready'
    code = '''import sys,time,subprocess
sys.stdin.readline()
from pathlib import Path
from desk.futu_task import task_guard,bounded_worker
with task_guard(Path(sys.argv[1])) as owned:
 assert owned
 Path(sys.argv[2]).write_text('ready')
 with open(Path(sys.argv[1])/'inner.log','wb') as log:
  bounded_worker([sys.executable,'-c',"import sys,time;sys.stdin.readline();time.sleep(60)"],60,log)
'''
    with (tmp_path / 'outer.log').open('wb') as log:
        with pytest.raises(subprocess.TimeoutExpired):
            bounded_worker([sys.executable, '-c', code, str(tmp_path / 'guard'), str(marker)], 2, log)
    assert marker.exists()
    with task_guard(tmp_path / 'guard') as owned:
        assert owned
