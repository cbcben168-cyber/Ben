"""All inputs are SYNTHETIC; never import the Futu SDK."""
import json
import threading
from pathlib import Path
import pytest
import core
from core import Inbox, Evidence, Limits, Stop, WINDOW, encoded
from collector import collect
from test_evidence import FakeClock, book, ticker


def crossed():
    return dict(book(), Ask=[[599., 2, 1, {}]])


class SyntheticAdapter:
    def __init__(self, inbox, messages=()):
        self.inbox = inbox
        self.messages = messages
    def connect(self): return 0, {}
    def state(self): return 0, {'qot_logined': True}
    def subscription(self): return 0, {'own_used': 2}
    def subscribe(self):
        for item in self.messages:
            self.inbox.submit('ORDER_BOOK', item, b'SYNTHETIC-PB')
        return 0, {}
    def pull(self, stream): return 0, {}
    def unsubscribe(self): return 0, {}
    def close(self): return 0, {}


def run_case(path, messages, limits=None, clock=None, extra=None):
    path.mkdir(exist_ok=True)
    (path/'INVOCATION_ONCE.json').write_bytes(b'{"mode":"SYNTHETIC"}')
    def factory(box):
        if extra: extra(box)
        return SyntheticAdapter(box, messages)
    return collect(path, {'window': WINDOW, 'mode': 'SYNTHETIC'},
                   clock or FakeClock(), factory, lambda: None, limits)


def test_isolated_cross_does_not_abort_window(tmp_path):
    out = run_case(tmp_path, [crossed(), book()])
    assert out['reason'] == 'WINDOW_COMPLETE'
    assert out['status'] == 'PARTIAL' and out['invalid'] == 1
    assert out['messages'] == 2 and out['book_versions'] == 1


def test_second_quality_error_does_not_abort_cleanup(tmp_path):
    messages = [crossed()] * 6 + [book()]
    out = run_case(tmp_path, messages)
    assert out['messages'] == len(messages)
    assert out['invalid'] == 6 and out['pending'] == 0
    assert out['status'] == 'PARTIAL'


@pytest.mark.parametrize('count', [1, 2, 3, 12])
def test_crosses_never_become_qualified_samples(tmp_path, count):
    out = run_case(tmp_path, [crossed()]*count + [book()])
    rows = [json.loads(x) for x in (tmp_path/'receipts.jsonl').read_bytes().splitlines()]
    assert out['invalid'] == count and out['book_versions'] == 1
    assert out['messages'] == count+1 and out['accounting']['unsaved_accepted'] == 0
    assert all(x['sample_status'] == 'INVALID' and x['invalid_reason'] == 'CROSSED_BOOK'
               for x in rows[:count])
    assert not out['minimum_usable'] and out['status'] == 'PARTIAL'
    assert (out['first_fatal'] == 'CROSSED_BUDGET_EXCEEDED') == (count >= 3)
    # Raw and decoded extents retain exactly the supplied bytes and sides.
    r = rows[0]
    for name, info in r['files'].items():
        data = (tmp_path/name).read_bytes()[info['offset']:info['offset']+info['bytes']]
        if name.endswith('pbb'): assert data == b'SYNTHETIC-PB'
        else: assert json.loads(data)['native'] == crossed()


@pytest.mark.parametrize('locked', [False, True])
def test_normal_and_locked_book_are_valid(tmp_path, locked):
    row = book()
    if locked: row['Ask'][0][0] = row['Bid'][0][0]
    out = run_case(tmp_path, [row])
    assert out['invalid'] == 0 and out['book_versions'] == 1
    r = json.loads((tmp_path/'receipts.jsonl').read_bytes())
    assert r['quality'][0]['spread_bps'] == (0 if locked else pytest.approx(.1666652778))


def test_phase_budgets_are_separate_and_frozen():
    p = core.QualityPolicy()
    for _ in range(10):
        p.observe('ORDER_BOOK', False, 'CROSSED_BOOK'); p.observe('ORDER_BOOK', False)
    for _ in range(5):
        p.observe('ORDER_BOOK', True, 'CROSSED_BOOK'); p.observe('ORDER_BOOK', True)
    with pytest.raises(Stop, match='CROSSED_BUDGET_EXCEEDED'):
        p.observe('ORDER_BOOK', True, 'CROSSED_BOOK')
    with pytest.raises(Stop, match='CROSSED_BUDGET_EXCEEDED'):
        p.observe('ORDER_BOOK', False, 'CROSSED_BOOK')
    assert core.digest((core.HERE/'POLICY.json').read_bytes()) == (core.HERE/'POLICY.sha256').read_text().strip()


def test_received_timestamp_selects_observation_policy(tmp_path):
    def extra(box):
        def hook():
            if box.clock.wall >= core.utc(WINDOW['start']):
                box.clock.hook = None
                for _ in range(3): box.submit('ORDER_BOOK', crossed(), b'SYNTHETIC')
        box.clock.hook = hook
    out = run_case(tmp_path, [], extra=extra)
    assert out['first_fatal'] == 'CROSSED_BUDGET_EXCEEDED'
    assert out['policy_counts'] == {'prewindow': 0, 'observation': 3}
    assert out['messages'] == 3 and out['accounting']['unsaved_accepted'] == 0


def test_non_cross_quality_error_stops_reception_but_drain_continues(tmp_path):
    bad = dict(book(), Bid=[])
    out = run_case(tmp_path, [bad, crossed(), bad, book()])
    assert out['first_fatal'] == 'EMPTY_BOOK'
    assert out['messages'] == 4 and out['invalid'] == 3
    assert len(out['cleanup_quality_errors']) == 2 and out['pending'] == 0


def test_queue_limit_drains_already_accepted(tmp_path):
    out = run_case(tmp_path, [book()]*4, Limits(queue_size=3))
    assert out['first_fatal'] == 'QUEUE_LIMIT' and out['status'] == 'PARTIAL'
    a = out['accounting']
    assert a['received'] == 4 and a['accepted'] == a['saved'] == 3
    assert a['rejected'] == 1 and a['unsaved_accepted'] == 0


def test_oversize_callback_stops_without_losing_prior_accepts(tmp_path):
    oversized = dict(book(), huge='x'*2048)
    out = run_case(tmp_path, [book(), oversized], Limits(message_bytes=1024))
    assert out['first_fatal'] == 'MESSAGE_LIMIT'
    assert out['accounting']['saved'] == 1 and out['accounting']['rejected'] == 1


@pytest.mark.parametrize('limits', [Limits(records=1), Limits(market_bytes=100), Limits(total_bytes=4*1024*1024)])
def test_resource_stop_retains_dequeued_and_pending_unsaved_counts(tmp_path, limits):
    out = run_case(tmp_path, [book()]*4, limits)
    assert out['first_fatal'] == 'RESOURCE_LIMIT' and out['status'] == 'PARTIAL'
    a = out['accounting']
    assert a['accepted'] == 4 == a['saved']+a['unsaved_accepted']
    assert a['unsaved_accepted'] == a['pending']+a['dequeued_unsaved'] > 0


@pytest.mark.parametrize('failure_at', [1, 2, 3, 4])
def test_batch_fsync_failure_never_counts_uncommitted_as_saved(tmp_path, monkeypatch, failure_at):
    from core import PackedEvidence
    store = PackedEvidence(tmp_path, FakeClock())
    box = Inbox(FakeClock()); box.submit('ORDER_BOOK', book(), b'SYNTHETIC')
    store.accept(box.q.get_nowait())
    real = core.os.fsync; calls = []
    def fail(fd):
        calls.append(fd)
        if len(calls) == failure_at: raise OSError('SYNTHETIC_IO_FAILURE')
        return real(fd)
    monkeypatch.setattr(core.os, 'fsync', fail)
    with pytest.raises(OSError): store.finish()
    assert store.durable_messages == 0 and store.commit_failed
    store.finish()  # no retry after a failed commit
    assert len(calls) == failure_at
    store.close()


def test_write_failure_keeps_initial_fatal_and_separate_cleanup_error(tmp_path, monkeypatch):
    real = core.PackedEvidence.write_payload
    count = []
    def fail(self, *args):
        count.append(1)
        if len(count) == 3: raise OSError('SYNTHETIC')
        return real(self, *args)
    monkeypatch.setattr(core.PackedEvidence, 'write_payload', fail)
    out = run_case(tmp_path, [dict(book(), Bid=[]), book(), book()])
    assert out['first_fatal'] == 'EMPTY_BOOK'
    assert 'WRITE_FAILED' in out['cleanup_errors']
    assert out['status'] == 'PARTIAL'
    assert out.get('accounting', out).get('unsaved_accepted') > 0
    assert out['receipt_head'] == core.verify_receipts(tmp_path)['receipt_head']


def test_close_and_admission_share_lock():
    entered = threading.Event(); release = threading.Event()
    class Bytes:
        def __bytes__(self):
            entered.set(); assert release.wait(2)
            return b'SYNTHETIC'
    box = Inbox(FakeClock())
    submit = threading.Thread(target=box.submit, args=('ORDER_BOOK', book(), Bytes()))
    submit.start(); assert entered.wait(2)
    close = threading.Thread(target=box.close_reception); close.start()
    release.set(); submit.join(2); close.join(2)
    accepted = box.accepted
    box.submit('ORDER_BOOK', book(), b'LATE_SYNTHETIC')
    assert not box.accepting and box.accepted == accepted == 1 and box.after_close == 1


def test_cleanup_time_limit_keeps_unsaved_count(tmp_path, monkeypatch):
    c = FakeClock(); real = core.PackedEvidence.accept
    def slow(self, *args, **kwargs):
        result = real(self, *args, **kwargs)
        c.advance(11)
        return result
    monkeypatch.setattr(core.PackedEvidence, 'accept', slow)
    out = run_case(tmp_path, [dict(book(), Bid=[]), book(), book()], clock=c)
    assert out['status'] == 'PARTIAL' and out['first_fatal'] == 'EMPTY_BOOK'
    assert 'CLEANUP_DEADLINE' in out['cleanup_errors']
    assert out['accounting']['unsaved_accepted'] > 0


def test_hard_deadline_never_extends_cleanup(tmp_path, monkeypatch):
    c = FakeClock(); real = core.PackedEvidence.write_payload
    def expire(self, *args):
        result = real(self, *args)
        c.advance(370)
        return result
    monkeypatch.setattr(core.PackedEvidence, 'write_payload', expire)
    out = run_case(tmp_path, [book()]*3, clock=c)
    assert out['first_fatal'] == 'HARD_DEADLINE' and out['status'] == 'PARTIAL'
    assert out['accounting']['saved'] == 0 and out['accounting']['unsaved_accepted'] == 3


def test_uncommitted_tail_is_not_complete_capture(tmp_path):
    store = core.PackedEvidence(tmp_path, FakeClock()); box = Inbox(FakeClock())
    for _ in range(3):
        box.submit('ORDER_BOOK', book(), b'SYNTHETIC'); store.accept(box.q.get_nowait())
    store.close()  # simulate process exit before commit, no fsync claim
    assert core.verify_receipts(tmp_path)['messages'] == 0


def test_no_live_default_entry(tmp_path):
    with pytest.raises(Stop, match='OFFLINE_INJECTION_REQUIRED'):
        collect(tmp_path, {'window': WINDOW})


def test_native_job_timeout_confirmed_inside_original_five_seconds(tmp_path):
    import sys, time
    from process_guard import Job
    script = tmp_path/'synthetic_blocked_worker.py'
    admitted = tmp_path/'ACCEPTED_SYNTHETIC.json'
    script.write_text('import sys,time\nfrom pathlib import Path\n'
        f'sys.path.insert(0,{str(core.HERE)!r})\n'
        'from core import Inbox,Clock,encoded,write_once\n'
        'box=Inbox(Clock())\n'
        'for i in range(10):box.submit("ORDER_BOOK",{"code":"US.SPY","SYNTHETIC":True},b"SYNTHETIC")\n'
        f'write_once(Path({str(admitted)!r}),encoded({{"mode":"SYNTHETIC","accepted":box.accepted}}))\n'
        'time.sleep(60)\n')
    start = time.perf_counter()
    job = Job([sys.executable, '-B', str(script)], tmp_path)
    try:
        while time.perf_counter()-start < 4.7:
            assert not job.wait(0)
            time.sleep(.005)
        job.stop()
        duration = time.perf_counter()-start
        assert duration < 5 and job.active_processes() == 0 and job.wait(0)
        received = json.loads(admitted.read_bytes())['accepted']
        saved = core.verify_receipts(tmp_path)['messages']
        assert received == 10 and saved == 0 and received-saved == 10
        (tmp_path/'FORCED_STOP_RESULT.json').write_bytes(encoded({
            'mode': 'SYNTHETIC', 'accepted': received, 'saved': saved,
            'unsaved_accepted': received-saved, 'active_owned_processes': 0,
            'termination_confirmed_seconds': duration}))
    finally: job.close()


def test_native_job_kills_only_owned_descendants(tmp_path):
    import os, sys, time
    from process_guard import Job
    script = tmp_path/'synthetic_child.py'
    marker = tmp_path/'child_ready'
    script.write_text('import subprocess,sys,time,os,json\nfrom pathlib import Path\n'
        'child=subprocess.Popen([sys.executable,"-B","-c","import time;time.sleep(60)"])\n'
        f'Path({str(marker)!r}).write_text(json.dumps({{"mode":"SYNTHETIC","parent_pid":os.getpid(),"child_pid":child.pid}}))\n'
        'time.sleep(60)\n')
    t = time.perf_counter(); job = Job([sys.executable, '-B', str(script)], tmp_path)
    try:
        while not marker.exists() and time.perf_counter()-t < 3: time.sleep(.01)
        assert marker.exists()
        identity = json.loads(marker.read_bytes())
        # Windows adds an owned conhost.exe; enumerate the Job, never guess count.
        import ctypes as ct
        class Pids(ct.Structure):
            _fields_ = [('assigned', ct.c_ulong), ('count', ct.c_ulong), ('ids', ct.c_size_t*16)]
        owned = Pids()
        assert job.k.QueryInformationJobObject(job.job, 3, ct.byref(owned), ct.sizeof(owned), None)
        known = {job.pid, identity['parent_pid'], identity['child_pid']}
        assert known <= set(owned.ids[:owned.count])
        assert owned.count == owned.assigned == job.active_processes()
        start = time.perf_counter(); job.stop()
        assert time.perf_counter()-start < .2 and job.active_processes() == 0 and job.wait(0)
        assert os.getpid() > 0
    finally: job.close()
