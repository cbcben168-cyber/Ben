"""Bridge-only OS metadata checks. Never import Futu, open sockets, or change tasks."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tomllib
import ctypes as ct
from ctypes import wintypes as wt

TASK = '__NO_SCHEDULED_TASK_FOR_THIS_MANUAL_RUN__'


def server_images(listeners):
    k = ct.WinDLL('kernel32', use_last_error=True)
    for name, args, result in [('OpenProcess', [wt.DWORD, wt.BOOL, wt.DWORD], wt.HANDLE),
        ('QueryFullProcessImageNameW', [wt.HANDLE, wt.DWORD, wt.LPWSTR, ct.POINTER(wt.DWORD)], wt.BOOL),
        ('CloseHandle', [wt.HANDLE], wt.BOOL)]:
        fn = getattr(k, name); fn.argtypes = args; fn.restype = result
    records = []
    for pid in sorted({row['pid'] for row in listeners}):
        handle = k.OpenProcess(0x1000, False, pid)
        if not handle: raise RuntimeError('SERVER_IMAGE_HANDLE_UNAVAILABLE')
        try:
            text = ct.create_unicode_buffer(32768); length = wt.DWORD(len(text))
            if not k.QueryFullProcessImageNameW(handle, 0, text, ct.byref(length)):
                raise RuntimeError('SERVER_IMAGE_QUERY_FAILED')
            path = Path(text.value)
            records.append({'pid': pid, 'image_path': str(path),
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        finally: k.CloseHandle(handle)
    return records


def automation_metadata():
    base = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex')))/'automations'
    if not base.is_dir():
        return {'complete': False, 'items': []}
    items = []
    for path in sorted(base.glob('*/automation.toml')):
        raw = path.read_bytes(); data = tomllib.loads(raw.decode('utf-8'))
        items.append({'id': path.parent.name, 'status': data.get('status'),
                      'rrule': data.get('rrule'), 'sha256': hashlib.sha256(raw).hexdigest()})
    return {'complete': True, 'items': items}


def stamp(text, offset=0):
    value = datetime.fromisoformat(text)
    return value.replace(tzinfo=timezone(timedelta(minutes=offset))) if value.tzinfo is None else value


STATUS_FIELDS = ('resource_isolation_proven', 'engineering_risk_accepted', 'known_conflict',
                 'unknown_external_clients', 'proceed_allowed')


def known_quota_insufficient(data):
    remaining = data.get('remain') if isinstance(data, dict) else None
    return type(remaining) in (int, float) and remaining <= 0


def entry_checks(policy):
    results = {}
    for key, rule in policy.get('verified_nonclient_tasks', {}).items():
        results[key] = all(Path(path).is_file() and hashlib.sha256(Path(path).read_bytes()).hexdigest() == expected
                           for path, expected in rule['file_hashes'].items())
    return results


def state_valid(state, risk_approved):
    if 'verified' in state: return False
    if any(type(state.get(k)) is not bool for k in
           ('resource_isolation_proven', 'engineering_risk_accepted', 'known_conflict', 'proceed_allowed')): return False
    if not isinstance(state.get('unknown_external_clients'), list): return False
    critical = state.get('critical_failures'); conflicts = state.get('known_conflicts')
    unknown_events = state.get('unknown_resource_events')
    if not all(isinstance(v, list) for v in (critical, conflicts, unknown_events)): return False
    if state['engineering_risk_accepted'] is not risk_approved: return False
    if state['known_conflict'] is not bool(conflicts): return False
    if any(not isinstance(x, dict) or x.get('status') != 'UNKNOWN' for x in state['unknown_external_clients']): return False
    proven = not (critical or conflicts or unknown_events or state['unknown_external_clients'])
    allowed = not critical and not conflicts and (proven or risk_approved)
    return state['resource_isolation_proven'] is proven and state['proceed_allowed'] is allowed


def assess(snapshot, automations, window, policy):
    critical = []; conflicts = []; unknown = []; clients = []; nonclients = []
    if snapshot.get('coverage_complete') is not True: critical.append('OS_METADATA_INCOMPLETE')
    if snapshot.get('timezone_id') != 'China Standard Time' or snapshot.get('local_offset_minutes') != 480:
        critical.append('OS_TIMEZONE_CHANGED')
    begin, end = stamp(window['launch_start']), stamp(window['cleanup_end'])
    offset = snapshot.get('local_offset_minutes', 480)
    tasks = {t['key']: t for t in snapshot.get('relevant_tasks', [])}
    protected = policy['protected_task_hashes']
    lifecycle = set(policy.get('service_lifecycle_tasks', []))
    for key, expected in protected.items():
        if tasks.get(key, {}).get('xml_sha256') != expected: critical.append('PROTECTED_TASK_CHANGED:'+key)
    for task in tasks.values():
        key = task['key']
        if key == TASK or not task.get('enabled'): continue
        rule = policy.get('verified_nonclient_tasks', {}).get(key)
        if rule and task.get('action_sha256') == rule['action_sha256'] and snapshot.get('entry_checks', {}).get(key) is True:
            nonclients.append({'task': key, 'classification': 'CONFIRMED_NONCONFLICT_DIRECT_OPEND_ONLY'}); continue
        known = key in protected and key not in lifecycle
        if task.get('state') == 'Running':
            (conflicts if known else unknown).append(('PROTECTED_ACTIVE_TASK:' if known else 'TASK_ACTIVE_PURPOSE_UNKNOWN:')+key)
        for trigger in task.get('triggers', []):
            if trigger.get('enabled') is False: continue
            if trigger.get('end') and stamp(trigger['end'], offset) < begin: continue
            if key in lifecycle:
                unknown.append('SERVICE_LIFECYCLE_EVENT_UNKNOWN:'+key); continue
            if trigger.get('type') != 'MSFT_TaskTimeTrigger' or trigger.get('repeat') or not trigger.get('start'):
                (critical if known else unknown).append(('PROTECTED_SCHEDULE_UNVERIFIABLE:' if known else 'TASK_SCHEDULE_UNKNOWN:')+key); continue
            start = stamp(trigger['start'], offset)
            if start >= end: continue
            if start < begin and task.get('start_when_available'):
                (critical if known else unknown).append('TASK_CATCHUP_UNKNOWN:'+key); continue
            duration = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', task.get('time_limit', ''))
            seconds = sum(int(n or 0)*scale for n, scale in zip(duration.groups(), [3600, 60, 1])) if duration else 0
            if seconds <= 0:
                (critical if known else unknown).append('TASK_DURATION_UNKNOWN:'+key); continue
            if start+timedelta(seconds=seconds) > begin:
                (conflicts if known else unknown).append(('PROTECTED_TASK_OVERLAP:' if known else 'TASK_POSSIBLE_OVERLAP:')+key)
    # The bridge has not connected yet. Any established server-side API connection is non-owned.
    if snapshot.get('clients'): conflicts.append('NONOWN_ACTIVE_OPEND_CONNECTION')
    if snapshot.get('quota_insufficient') is True: conflicts.append('KNOWN_QUOTA_INSUFFICIENT')
    if snapshot.get('permission_denied') is True: critical.append('PERMISSION_DENIED')
    if snapshot.get('quota_status') != 'VERIFIED_AVAILABLE': unknown.append('QUOTA_NOT_AVAILABLE_PRECONNECT')
    servers = snapshot.get('servers', [])
    if len(servers) != 1 or servers[0].get('sha256') != policy['opend_executable_sha256']:
        critical.append('OPEND_SERVER_IDENTITY_UNKNOWN')
    processes = snapshot.get('processes', []); by_pid = {p['pid']: p for p in processes}
    own = {snapshot.get('owner_pid')}; current = snapshot.get('owner_pid')
    while current in by_pid and by_pid[current]['parent_pid'] not in own:
        current = by_pid[current]['parent_pid']; own.add(current)
    family = {snapshot.get('owner_pid')}
    for _ in range(len(processes)):
        extra = {p['pid'] for p in processes if p['parent_pid'] in family}-family
        if not extra: break
        family |= extra
    own |= family
    server_pids = {s.get('pid') for s in servers}
    for process in processes:
        if process['pid'] in own | server_pids: continue
        if re.match(r'(?i)^(pythonw?|py|powershell|pwsh|cmd|wscript|cscript|futu.*|.*opend.*)\.exe$', process.get('name', '')):
            clients.append({'pid': process['pid'], 'status': 'UNKNOWN', 'reason': 'FUTURE_CLIENT_BEHAVIOR_UNPROVEN'})
    if automations.get('complete') is not True: critical.append('AUTOMATION_METADATA_INCOMPLETE')
    weekday = begin.astimezone(timezone(timedelta(hours=8))).weekday()
    days = ['MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU']
    for item in automations.get('items', []):
        if item.get('status') == 'PAUSED': continue
        parts = dict(part.split('=', 1) for part in str(item.get('rrule', '')).removeprefix('RRULE:').split(';') if '=' in part)
        if item.get('status') != 'ACTIVE' or parts.get('FREQ') != 'WEEKLY' or not parts.get('BYDAY'):
            unknown.append('AUTOMATION_SCHEDULE_UNKNOWN:'+item['id']); continue
        if days[weekday] in parts['BYDAY'].split(','): unknown.append('AUTOMATION_POSSIBLE_OVERLAP:'+item['id'])
    critical = sorted(set(critical)); conflicts = sorted(set(conflicts)); unknown = sorted(set(unknown))
    accepted = policy.get('engineering_risk_accepted') is True
    proven = not (critical or conflicts or unknown or clients)
    return {'schema': 'D2_RESOURCE_CHECK_V3', 'resource_isolation_proven': proven,
            'engineering_risk_accepted': accepted, 'known_conflict': bool(conflicts),
            'unknown_external_clients': clients, 'proceed_allowed': not critical and not conflicts and (proven or accepted),
            'critical_failures': critical, 'known_conflicts': conflicts, 'unknown_resource_events': unknown,
            'verified_nonclient_entries': nonclients, 'window': window, 'assessed_at_utc': snapshot['observed_at_utc'],
            'snapshot_sha256': None, 'entitlement': 'NOT_VERIFIED', 'clock_qualification': 'NOT_VERIFIED',
            'absolute_window_isolation_claimed': False}


def collect(here, powershell, deadline, clock):
    from process_guard import Job
    output = here/'RUNTIME_ISOLATION_SNAPSHOT.json'
    job = Job([powershell, '-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-File',
               str(here/'read_resource_metadata.ps1'), '-OutputPath', str(output), '-OwnerPid', str(os.getpid())], here.parents[1])
    initial = clock.stamp()
    try:
        while not job.wait(0):
            now = clock.stamp()
            elapsed = (now['monotonic_ns']-initial['monotonic_ns'])/1e9
            if elapsed < 0 or abs((stamp(now['utc'])-stamp(initial['utc'])).total_seconds()-elapsed) > 1:
                raise RuntimeError('PREFLIGHT_CLOCK_CHANGED')
            # Allocate within the frozen 20s launch window; never extend that window.
            if elapsed >= 12 or stamp(now['utc']) >= stamp(deadline)-timedelta(seconds=1):
                raise RuntimeError('PREFLIGHT_DEADLINE')
            clock.sleep(.02)
        if job.exitcode() != 0 or output.stat().st_size > 393216: raise RuntimeError('PREFLIGHT_METADATA_FAILED')
        raw = output.read_bytes()
        snapshot = json.loads(raw)
        snapshot['file_sha256'] = hashlib.sha256(raw).hexdigest()
        snapshot['servers'] = server_images(snapshot['listeners'])
        snapshot['entry_checks'] = entry_checks(json.loads((here/'RUNTIME_ISOLATION_POLICY_V3.json').read_bytes()))
        record = {'servers': snapshot['servers'], 'entry_checks': snapshot['entry_checks'], 'observed': clock.stamp(), 'source': 'QueryFullProcessImageNameW_READ_ONLY'}
        encoded = json.dumps(record, sort_keys=True).encode('utf-8')
        with (here/'RUNTIME_SERVER_IDENTITY.json').open('xb') as stream:
            stream.write(encoded); stream.flush(); os.fsync(stream.fileno())
        snapshot['server_identity_sha256'] = hashlib.sha256(encoded).hexdigest()
        return snapshot, automation_metadata()
    finally:
        try:
            if not job.wait(0): job.stop()
        finally: job.close()
