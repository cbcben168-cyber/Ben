"""Opt-in bounded scheduler adapter for the unchanged PR #50 update engine."""
import argparse
from datetime import datetime, time as day_time, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.futu_daily_runtime import load_config, require_unattended, bounded_login, launch_environment
from desk.clock import ET
from desk.daily_update import latest_completed
from desk.futu_task import task_guard, bounded_worker
from desk.futu_update import FutuVersions, start_update, task_status, read_json, _atomic_json

TOTAL_SECONDS = 1500
ATTEMPT_SECONDS = 650
BACKOFF_SECONDS = 60


def eligible_target(now):
    """Only run after 06:30 UTC and before 09:00 New York; never an open NY date."""
    if now.tzinfo is None:
        raise ValueError('Scheduling time must include a timezone')
    now = now.astimezone(timezone.utc)
    local = now.astimezone(ET)
    if now.time().replace(tzinfo=None) < day_time(6, 30) or local.time() >= day_time(9):
        return None
    target = latest_completed(now)
    if target >= local.date().isoformat():
        return None
    return target


def retryable(result):
    # The old engine does not expose structured supplier errors. Unknown errors
    # (including generic capture exit codes) deliberately do not auto-retry.
    return result.get('status') == 'BUSY' or (
        result.get('status') == 'FAILED' and
        result.get('reason') == 'Futu OpenD响应超时，请检查连接后重试。')


def update_once(config, versions, target, clock=time.monotonic, sleep=time.sleep):
    if not start_update(versions, ROOT / 'scripts/update_futu_daily.py', python=config['python']):
        return dict(status='BUSY', reason='Existing web or scheduled update owns the engine')
    token = read_json(versions.lock).get('token')
    if not isinstance(token, str) or len(token) != 32 or any(c not in '0123456789abcdef' for c in token):
        return dict(status='FAILED', reason='Cannot identify the newly started engine token')
    deadline = clock() + ATTEMPT_SECONDS
    while clock() < deadline:
        # A pointer commit is authoritative even if status/receipt writing failed.
        committed = versions.pointer_data().get('result', {})
        result = committed if committed.get('token') == token else read_json(
            versions.root / ('result_' + token + '.json'))
        if result.get('token') == token:
            if result.get('status') in {'SUCCESS', 'UP_TO_DATE'}:
                current = versions.summary(validate=True)
                if current['last'] != target:
                    return dict(status='FAILED', token=token, reason='Engine target differs from scheduled safe target')
            return dict(result, token=token)
        running, status = task_status(versions)
        if not running and status.get('token') == token and status.get('status') == 'FAILED':
            return status
        sleep(.5)
    # The outer owned Job Object is closed when this worker exits. Do not retry
    # or terminate by PID, and never touch an unrelated web-button process.
    return dict(status='FAILED', token=token, reason='Scheduled attempt exceeded its wait deadline')


def run_cycle(config, now=None, login=bounded_login, update=update_once, sleep=time.sleep):
    require_unattended(config)
    versions = FutuVersions(config['environment']['ICT_FUTU_DAILY_ARCHIVE'],
                            config['environment']['ICT_FUTU_DAILY_ROOT'])
    target = eligible_target(now or datetime.now(timezone.utc))
    if target is None:
        return dict(status='DEFERRED', reason='Outside the safe catch-up window')
    current = versions.summary(validate=True)
    if current['last'] > target:
        return dict(status='FAILED', target=target, reason='Archive date is ahead of the safe target')
    if current['last'] == target:
        return dict(status='SKIPPED', target=target, reason='Target already covered; no supplier request')
    directory = versions.root / 'scheduler'
    with task_guard(directory) as owned:
        if not owned:
            return dict(status='BUSY', target=target, reason='Another scheduler owns the daily budget')
        state_path = directory / ('day_' + target + '.json')
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding='utf-8'))
            if state.get('target') != target or type(state.get('attempts')) is not int or not 0 <= state['attempts'] <= 2:
                raise ValueError('Corrupt daily attempt ledger; operator review required')
        else:
            state = dict(target=target, attempts=0)
        if state.get('terminal'):
            return dict(status='FAILED', target=target, reason='Daily terminal failure requires operator review')
        while state['attempts'] < 2:
            began = time.monotonic()
            attempt = state['attempts'] + 1
            # Reserve before doing any work: crash/reboot cannot reset the budget.
            state.update(attempts=attempt, status='RUNNING', started_at=datetime.now(timezone.utc).isoformat())
            _atomic_json(state_path, state)
            before = versions.current()[1]
            with (directory / f'login_{target}_{attempt}.log').open('ab') as log:
                try:
                    ready = login(config, log)
                except (subprocess.TimeoutExpired, OSError):
                    ready = False
            if not ready:
                result = dict(status='FAILED', reason='OpenD quote login unavailable; no update started')
            else:
                # Real time is checked again after potentially slow login/backoff.
                safe = eligible_target(now or datetime.now(timezone.utc))
                result = (update(config, versions, target) if safe == target else
                          dict(status='DEFERRED', reason='Safe target/window changed before engine start'))
            record = dict(result, target=target, attempt=attempt, before=before,
                          after=versions.current()[1], started_at=state['started_at'],
                          finished_at=datetime.now(timezone.utc).isoformat(),
                          elapsed_seconds=round(time.monotonic() - began, 3),
                          phase=result.get('phase', 'engine' if ready else 'quote_login'),
                          exit_code=0 if result['status'] in {'SUCCESS', 'UP_TO_DATE', 'DEFERRED'} else 1)
            _atomic_json(directory / f'attempt_{target}_{attempt}.json', record)
            state.update(status=result['status'], token=result.get('token'),
                         terminal=not retryable(result), finished_at=record['finished_at'])
            _atomic_json(state_path, state)
            if result['status'] in {'SUCCESS', 'UP_TO_DATE'} or not retryable(result):
                return record
            if state['attempts'] < 2:
                sleep(BACKOFF_SECONDS)
        return dict(status='FAILED', target=target, reason='Two-attempt daily budget exhausted')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--run', action='store_true', help='Explicit opt-in; default only validates configuration')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.worker and sys.stdin.readline().strip() != 'GO':
        return 2
    try:
        config = load_config(args.config)
        if not args.run:
            print(json.dumps(dict(status='CONFIG_VALID', enabled=config['unattended_enabled'])))
            return 0
        require_unattended(config)
        environment = launch_environment(config)
        os.environ.clear()
        os.environ.update(environment)
        directory = Path(config['environment']['ICT_FUTU_DAILY_ROOT']) / 'scheduler'
        directory.mkdir(exist_ok=True)
        if args.worker:
            try:
                result = run_cycle(config)
            except Exception as exc:
                result = dict(status='FAILED', reason='Scheduled worker exception: ' + type(exc).__name__)
            _atomic_json(directory / 'latest.json', result)
            return 0 if result['status'] in {'SUCCESS', 'UP_TO_DATE', 'SKIPPED', 'DEFERRED'} else 1
        invocation = uuid.uuid4().hex
        with (directory / ('supervisor_' + invocation + '.log')).open('wb') as log:
            try:
                return bounded_worker([config['python'], '-B', str(Path(__file__).resolve()),
                                       '--config', str(args.config.resolve()), '--run', '--worker'],
                                      TOTAL_SECONDS, log)
            except subprocess.TimeoutExpired:
                _atomic_json(directory / ('failure_' + invocation + '.json'),
                             dict(status='FAILED', reason='Entire scheduled process tree exceeded 1500 seconds'))
                return 1
    except Exception as exc:
        # Allowlisted messages only; arbitrary config/SDK exceptions may contain secrets.
        print('Scheduled update refused: ' + type(exc).__name__, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
