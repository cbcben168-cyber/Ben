"""Read-only OS preflight, bounded by an owned Job. No Futu import or socket."""
import ctypes as ct
import json
import os
from core import Clock, Stop, encoded, file_sha, require, utc, write_once
from live_entry import HERE, WINDOW, CUTOFF, validate_safety
import runtime_isolation as runtime


def inspect_once():
    require(os.name == 'nt', 'WINDOWS_REQUIRED')
    require(not (HERE/'PREFLIGHT.json').exists(), 'PREFLIGHT_ALREADY_USED')
    clock = Clock()
    require(utc(clock.stamp()['utc']) < utc(CUTOFF), 'SEAL_DEADLINE_MISSED')
    policy = json.loads((HERE/'RUNTIME_ISOLATION_POLICY_V3.json').read_bytes())
    powershell = policy['powershell_path']
    require(file_sha(powershell) == policy['powershell_executable_sha256'], 'POWERSHELL_IDENTITY_CHANGED')
    initial = clock.stamp()
    deadline = (utc(initial['utc'])+runtime.timedelta(seconds=14)).isoformat()
    snapshot, automations = runtime.collect(HERE, powershell, deadline, clock)
    state = runtime.assess(snapshot, automations, WINDOW, policy)
    kernel = ct.WinDLL('kernel32', use_last_error=True)
    kernel.GetTickCount64.restype = ct.c_ulonglong
    tick = kernel.GetTickCount64()
    state.update(windows_awake=bool(tick > 0), windows_uptime_ms=tick,
        awake_evidence='executing Windows kernel query; future sleep not guaranteed; loop-gap watchdog required',
        identity_verified=not any('IDENTITY' in x or 'CHANGED' in x for x in state['critical_failures']),
        snapshot_sha256=snapshot['file_sha256'], risk_acceptance_inherited=False,
        assessed_at_utc=clock.stamp()['utc'], collection_started=initial,
        opend_login='NOT_CHECKED_BEFORE_RESOURCE_GATE', quote_entitlement='NOT_CHECKED_BEFORE_RESOURCE_GATE',
        automations=automations)
    write_once(HERE/'PREFLIGHT.json', encoded(state))
    validate_safety(state, clock.stamp()['utc'])
    return state


if __name__ == '__main__':
    try:
        result = inspect_once()
        print(json.dumps({'status': 'PASS', 'assessed_at_utc': result['assessed_at_utc']}))
    except Exception as exc:
        print(json.dumps({'status': 'BLOCKED', 'reason': str(exc) if isinstance(exc, Stop) else 'PREFLIGHT_METADATA_FAILED'}))
        raise SystemExit(2)
