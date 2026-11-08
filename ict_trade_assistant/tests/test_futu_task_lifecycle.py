import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest

from desk.futu_task import task_guard, bounded_worker
from desk.futu_update import (FutuVersions, start_update, task_status, run_update,
                              _atomic_json, read_json)
from test_futu_update_v045 import setup, capture, make_payload, TICKERS


def test_os_owner_blocks_cleanup_even_with_old_or_reused_pid(setup):
    versions, _ = setup
    _atomic_json(versions.lock, dict(token='owned', created=0, pid=os.getpid()))
    command = [sys.executable, '-u', '-c',
               "from desk.futu_task import task_guard; import sys; from pathlib import Path; "
               "g=task_guard(Path(sys.argv[1])); assert g.__enter__(); print('READY',flush=True); "
               "sys.stdin.readline(); g.__exit__(None,None,None)", str(versions.root)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        assert process.stdout.readline().strip() == b'READY'
        assert task_status(versions)[0]
        assert not start_update(versions, Path('scripts/update_futu_daily.py'))
        assert read_json(versions.lock)['token'] == 'owned'
    finally:
        process.stdin.close(); process.wait(timeout=5)
    # No PID is probed: even a marker naming this live test process is recoverable.
    running, status = task_status(versions)
    assert not running and status['status'] == 'FAILED'
    assert not versions.lock.exists()


@pytest.mark.parametrize('phase', ['capture', 'validation', 'publication'])
def test_complete_process_tree_timeout_is_bounded(tmp_path, phase):
    marker = tmp_path/'child.pid'
    code = ("import sys,subprocess,time; sys.stdin.readline(); "
            "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
            "open(sys.argv[1],'w').write(str(p.pid)); time.sleep(60)")
    began = time.monotonic()
    with (tmp_path/'log.txt').open('wb') as log:
        with pytest.raises(subprocess.TimeoutExpired):
            bounded_worker([sys.executable, '-c', code, str(marker), phase], .7, log)
    assert time.monotonic() - began < 8
    assert marker.exists()
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.restype = wintypes.HANDLE
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x1000, False, int(marker.read_text()))
        if handle:
            exit_code = wintypes.DWORD()
            try:
                assert api.GetExitCodeProcess(handle, ctypes.byref(exit_code))
                assert exit_code.value != 259  # STILL_ACTIVE
            finally:
                api.CloseHandle(handle)


def test_committed_version_survives_final_status_write_failure(setup, tmp_path, monkeypatch):
    import desk.futu_update as module
    versions, _ = setup
    packets = [make_payload(t, '2026-02-06') for t in TICKERS]
    directory = capture(tmp_path/'packets', packets)
    original = module._atomic_json
    def fail_status(path, value):
        if path == versions.status and value.get('status') == 'SUCCESS':
            raise PermissionError('simulated status file failure')
        return original(path, value)
    monkeypatch.setattr(module, '_atomic_json', fail_status)
    result = run_update(versions, Path('unused'), now='2026-02-06T22:00:00Z',
                        capture_dir=directory, token='status_failure')
    assert result['status'] == 'SUCCESS'
    assert result['status_warning']
    running, recovered = task_status(versions)
    assert not running and recovered['status'] == 'SUCCESS'
    assert versions.summary()['last'] == '2026-02-06'


def test_failed_worker_can_retry_without_stale_progress(setup, tmp_path, monkeypatch):
    versions, packets = setup
    directory = capture(tmp_path/'packets', packets)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], .1)
    monkeypatch.setattr('desk.futu_update.subprocess.run', timeout)
    result = run_update(versions, Path('unused'), now='2026-02-05T22:00:00Z', token='failed')
    assert result['status'] == 'FAILED' and '超时' in result['reason']
    assert versions.current()[1] == 'baseline'
    result = run_update(versions, Path('unused'), now='2026-02-05T22:00:00Z',
                        capture_dir=directory, token='retry')
    assert result['status'] == 'UP_TO_DATE'
    assert not (versions.root/'capture_progress.json').exists()


def test_reservation_blocks_two_fast_clicks_and_stale_marker_recovers(setup, monkeypatch):
    versions, _ = setup
    calls = []
    monkeypatch.setattr('desk.futu_update.subprocess.Popen', lambda *a, **k: calls.append(a))
    assert start_update(versions, Path('scripts/update_futu_daily.py'))
    assert not start_update(versions, Path('scripts/update_futu_daily.py'))
    assert len(calls) == 1
    lock = read_json(versions.lock); lock['created'] = 0
    _atomic_json(versions.lock, lock)
    assert not task_status(versions)[0]
    assert start_update(versions, Path('scripts/update_futu_daily.py'))
    assert len(calls) == 2


def test_validation_hang_after_capture_is_terminated(tmp_path):
    root = tmp_path/'versions'
    code = '''import sys,time
sys.stdin.readline()
from pathlib import Path
import desk.futu_update as m
v=m.FutuVersions(Path(sys.argv[1])/'unused.sqlite3',Path(sys.argv[1]))
v.summary=lambda:dict(first='2026-01-05')
m.publish_capture=lambda *a,**k:time.sleep(60)
m.run_update(v,Path('unused'),now='2026-02-05T22:00:00Z',capture_dir=Path('saved'),token='hung_validation')
'''
    with (tmp_path/'worker.log').open('wb') as log:
        with pytest.raises(subprocess.TimeoutExpired):
            bounded_worker([sys.executable, '-c', code, str(root)], 5, log)
    assert '校验' in read_json(root/'status.json')['phase']
    assert not (root/'current.json').exists()


def test_corrupt_marker_is_recoverable_without_pid_probe(setup):
    versions, _ = setup
    versions.root.mkdir(parents=True, exist_ok=True)
    versions.lock.write_text('{broken',encoding='utf-8')
    running, status = task_status(versions)
    assert not running and status['status']=='FAILED'
    assert not versions.lock.exists()


def test_actual_capture_child_exit_is_reported_and_retry_is_possible(setup, tmp_path):
    versions, _ = setup
    child = tmp_path/'exit_capture.py'
    child.write_text('raise SystemExit(7)', encoding='utf-8')
    result = run_update(versions, child, now='2026-02-05T22:00:00Z', token='exit_child')
    assert result['status']=='FAILED'
    assert versions.current()[1]=='baseline'
    assert not task_status(versions)[0]
