"""Offline entry tests: no Futu import or network is permitted by conftest."""
import json
import sys
import pytest

from core import Stop, encoded, digest


def test_default_has_no_live_authority():
    from live_entry import main
    assert main([]) == 0
    assert 'futu' not in sys.modules


def test_no_authorization_never_connects(tmp_path):
    from live_entry import validate_bundle
    with pytest.raises(Stop, match='LIVE_AUTHORIZATION_REQUIRED'):
        validate_bundle(tmp_path, '2026-10-27T19:34:00+00:00')


def fixture_bundle(path):
    from live_entry import WINDOW, RUN, identity, CONTRACT, POLICY_SHA
    contract = dict(CONTRACT)
    source = identity()
    auth = {'run_id': RUN, 'live_authorized': True, 'single_use': True,
            'contract_sha256': digest(encoded(contract)), 'policy_sha256': POLICY_SHA,
            'source_sha256': digest(encoded(source)), 'window': WINDOW,
            'sealed_at_utc': '2026-10-27T19:30:00+00:00',
            'human_instruction': 'FUTU D2 final live integration; conditional one shot',
            'risk_acceptance_inherited': False}
    for name, value in [('LIVE_CONTRACT.json', contract), ('SOURCE_IDENTITY.json', source),
                        ('ONE_SHOT_AUTHORIZATION.json', auth)]:
        (path/name).write_bytes(encoded(value))
    return auth


@pytest.mark.parametrize('key,value,reason', [
    ('run_id', 'OLD_RUN', 'AUTHORITY_IDENTITY_MISMATCH'),
    ('live_authorized', False, 'AUTHORITY_IDENTITY_MISMATCH'),
    ('source_sha256', '0'*64, 'SOURCE_IDENTITY_MISMATCH'),
    ('policy_sha256', '0'*64, 'POLICY_IDENTITY_MISMATCH'),
    ('contract_sha256', '0'*64, 'CONTRACT_IDENTITY_MISMATCH'),
    ('window', {}, 'WINDOW_IDENTITY_MISMATCH'),
    ('sealed_at_utc', '2026-10-27T19:35:00+00:00', 'SEAL_DEADLINE_MISSED'),
    ('risk_acceptance_inherited', True, 'OLD_RISK_ACCEPTANCE_FORBIDDEN'),
])
def test_mismatched_authority_denied(tmp_path, key, value, reason):
    from live_entry import validate_bundle
    auth = fixture_bundle(tmp_path); auth[key] = value
    (tmp_path/'ONE_SHOT_AUTHORIZATION.json').write_bytes(encoded(auth))
    with pytest.raises(Stop, match=reason):
        validate_bundle(tmp_path, '2026-10-27T19:34:00+00:00')


def test_expired_window_denied(tmp_path):
    from live_entry import validate_bundle
    fixture_bundle(tmp_path)
    with pytest.raises(Stop, match='LAUNCH_WINDOW'):
        validate_bundle(tmp_path, '2026-10-27T19:34:21+00:00')


def test_modified_source_denied(tmp_path):
    from live_entry import validate_bundle
    fixture_bundle(tmp_path)
    (tmp_path/'SOURCE_IDENTITY.json').write_bytes(b'{}')
    with pytest.raises(Stop, match='SOURCE_IDENTITY_MISMATCH'):
        validate_bundle(tmp_path, '2026-10-27T19:34:00+00:00')


def test_valid_identity_then_duplicate_denied(tmp_path):
    from live_entry import validate_bundle, claim, RUN
    fixture_bundle(tmp_path)
    assert validate_bundle(tmp_path, '2026-10-27T19:34:00+00:00')['run_id'] == RUN
    folder = tmp_path/'runs'/RUN; folder.parent.mkdir()
    claim(folder, {})
    with pytest.raises(Stop, match='RUN_ALREADY_EXISTS'):
        claim(folder, {})


def test_real_path_has_no_injected_factory(tmp_path):
    import inspect
    from collector import collect_live
    assert 'factory' not in inspect.signature(collect_live).parameters
    with pytest.raises(Stop, match='LIVE_WORKER_CAPABILITY_REQUIRED'):
        collect_live(tmp_path, {})


def test_real_identity_is_written_before_hashing(tmp_path):
    from core import PackedEvidence, Inbox, verify_receipts
    from test_evidence import FakeClock, book
    clock = FakeClock(); box = Inbox(clock)
    store = PackedEvidence(tmp_path, clock, evidence_mode='REAL_QUOTE_ENGINEERING_OBSERVATION')
    box.submit('ORDER_BOOK', book(), b'OFFLINE_FIXTURE')
    store.accept(box.q.get_nowait()); store.finish(); store.close()
    receipt = json.loads((tmp_path/'receipts.jsonl').read_bytes())
    commit = json.loads((tmp_path/'commits.jsonl').read_bytes())
    assert receipt['mode'] == commit['mode'] == 'REAL_QUOTE_ENGINEERING_OBSERVATION'
    assert verify_receipts(tmp_path)['messages'] == 1


@pytest.mark.parametrize('change', ['stale', 'unknown', 'conflict', 'asleep', 'identity', 'window'])
def test_safety_gate_fails_closed(change):
    from live_entry import validate_safety, WINDOW
    state = {'assessed_at_utc': '2026-10-27T19:34:00+00:00', 'window': WINDOW,
        'resource_isolation_proven': True, 'engineering_risk_accepted': False,
        'proceed_allowed': True, 'known_conflict': False, 'unknown_external_clients': [],
        'critical_failures': [], 'known_conflicts': [], 'unknown_resource_events': [],
        'windows_awake': True, 'identity_verified': True}
    if change == 'stale': state['assessed_at_utc'] = '2026-10-27T19:32:00+00:00'
    if change == 'unknown': state['unknown_external_clients'] = [{'status': 'UNKNOWN'}]
    if change == 'conflict': state['known_conflicts'] = ['CONFLICT']
    if change == 'asleep': state['windows_awake'] = False
    if change == 'identity': state['identity_verified'] = False
    if change == 'window': state['window'] = {}
    with pytest.raises(Stop): validate_safety(state, '2026-10-27T19:34:01+00:00')


class HangingJob:
    def __init__(self): self.stopped = False
    def wait(self, milliseconds=0): return self.stopped
    def stop(self): self.stopped = True
    def exitcode(self): return 2
    def active_processes(self): return 0 if self.stopped else 1


def test_supervisor_bounds_blocking_sdk(tmp_path):
    from live_entry import monitor
    from core import control
    from test_evidence import FakeClock
    clock = FakeClock('2026-10-27T19:34:00+00:00'); job = HangingJob()
    control(tmp_path, {'in_call': True, 'started': clock.stamp()})
    result = monitor(job, tmp_path, clock)
    assert result['reason'] == 'SDK_TIMEOUT' and result['active_owned_processes'] == 0


def test_supervisor_corruption_kills_owned_job(tmp_path):
    from live_entry import monitor
    from test_evidence import FakeClock
    (tmp_path/'CONTROL.jsonl').write_bytes(b'invalid\n')
    job = HangingJob()
    result = monitor(job, tmp_path, FakeClock('2026-10-27T19:34:00+00:00'))
    assert result['reason'] == 'SUPERVISOR_CONTROL_FAILED' and job.stopped


def test_forced_exit_keeps_partial_manifest(tmp_path):
    from live_entry import finalize
    (tmp_path/'partial.pb').write_bytes(b'partial')
    result = finalize(tmp_path, {'reason': 'SDK_TIMEOUT', 'child_exitcode': 2, 'active_owned_processes': 0})
    assert result['status'] == 'PARTIAL' and result['collection'] is None
    manifest = json.loads((tmp_path/'MANIFEST.json').read_bytes())
    assert manifest['files']['partial.pb']['sha256'] == digest(b'partial')
    assert result['formal_orderflow_research'] == 'NOT_QUALIFIED'


@pytest.mark.parametrize('slot', ['connect', 'state', 'subscription', 'subscribe', 'pull_TICKER', 'pull_ORDER_BOOK'])
def test_every_sdk_exception_attempts_close(tmp_path, slot):
    from test_collector import run
    result, adapter = run(tmp_path, exception=slot)
    assert result['status'] == 'PARTIAL' and adapter.closed
    assert len(result['calls_used']) <= 9


def test_close_survives_evidence_fsync_failure(tmp_path, monkeypatch):
    import core
    from collector import collect
    from test_collector import FakeAdapter
    from test_evidence import FakeClock
    (tmp_path/'INVOCATION_ONCE.json').write_bytes(b'{}')
    keep = []
    def factory(box):
        adapter = FakeAdapter(box); keep.append(adapter); return adapter
    real = core.os.fsync; count = [0]
    def fail(fd):
        count[0] += 1
        if count[0] >= 2: raise OSError('OFFLINE_IO_FAILURE')
        return real(fd)
    monkeypatch.setattr(core.os, 'fsync', fail)
    result = collect(tmp_path, {'window': core.WINDOW}, FakeClock(), factory, lambda: None)
    assert keep[0].closed and result['status'] == 'PARTIAL'


def test_terminal_block_cannot_be_reopened(tmp_path):
    from live_entry import validate_bundle
    fixture_bundle(tmp_path)
    (tmp_path/'TERMINAL.json').write_bytes(b'{}')
    with pytest.raises(Stop, match='RUN_TERMINALLY_BLOCKED'):
        validate_bundle(tmp_path, '2026-10-27T19:34:00+00:00')


def test_contract_cannot_expand_budgets(tmp_path):
    from live_entry import validate_bundle
    auth = fixture_bundle(tmp_path)
    contract = json.loads((tmp_path/'LIVE_CONTRACT.json').read_bytes())
    contract['budgets']['sdk_calls'] = 10
    data = encoded(contract); (tmp_path/'LIVE_CONTRACT.json').write_bytes(data)
    auth['contract_sha256'] = digest(data)
    (tmp_path/'ONE_SHOT_AUTHORIZATION.json').write_bytes(encoded(auth))
    with pytest.raises(Stop, match='CONTRACT_IDENTITY_MISMATCH'):
        validate_bundle(tmp_path, '2026-10-27T19:34:00+00:00')


def test_production_entry_contains_no_factory_replacement():
    import inspect
    from collector import collect_live, _collect
    source = inspect.getsource(collect_live)
    engine = inspect.getsource(_collect)
    assert 'from sdk_adapter import Adapter' in engine and 'adapter = Adapter(inbox)' in engine
    assert 'validate_worker(folder, config)' in source
    assert 'None, None, tcp_once' in source


@pytest.mark.parametrize('status', ['missing', 'failed_xml', 'wrong_source', 'valid'])
def test_acceptance_gate_checks_saved_test_result(tmp_path, status):
    from live_entry import validate_acceptance
    auth = {'source_sha256': 'bound-source', 'sealed_at_utc': '2026-10-27T19:30:00+00:00'}
    if status == 'missing':
        with pytest.raises(Stop, match='OFFLINE_ACCEPTANCE_REQUIRED'): validate_acceptance(tmp_path, auth)
        return
    (tmp_path/'artifacts').mkdir()
    xml = f'<testsuites><testsuite tests="100" failures="{1 if status == "failed_xml" else 0}" errors="0" skipped="0"/></testsuites>'.encode()
    (tmp_path/'artifacts/sealed_tests.xml').write_bytes(xml)
    acceptance = dict(auth, status='PASS', tests_sha256=digest(xml))
    if status == 'wrong_source': acceptance['source_sha256'] = 'different'
    (tmp_path/'ENTRY_ACCEPTANCE.json').write_bytes(encoded(acceptance))
    if status == 'valid': validate_acceptance(tmp_path, auth)
    else:
        with pytest.raises(Stop): validate_acceptance(tmp_path, auth)
