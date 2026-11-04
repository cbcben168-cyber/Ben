"""仅验证RTH控制器故障；模拟时钟不能授予真实行情资格。"""
import importlib
import json
import os
import ctypes
import hashlib
import socket
import struct
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
m = importlib.import_module(os.environ.get('RTH_TEST_MODULE', 'rth_recovery_v3'))


def execute(tmp_path, guard=None, clock=None):
    plan = m.Plan('2026-11-03')
    clock = clock or m.SimClock(plan.start)
    reader = m.SimulationReader(plan, 'F')
    engine = m.Controller(plan, tmp_path, reader, clock, guard or (lambda: {'health_status': 200}),
                          lambda: {'protected': {}, 'observations': {}, 'events': []}, True)
    result = engine.run()
    return plan, reader, result, engine


def absent():
    raise m.TemporaryServiceError('SERVICE_ABSENT_NO_AUTOSTART')


def test_missing_service_does_not_prevent_independent_diagnostic(tmp_path):
    _, reader, result, _ = execute(tmp_path, absent)
    assert reader.calls, '8501缺失仍必须尝试独立行情诊断'
    assert result['real_rth_samples'] == 0
    assert result['items']['版本与端口']['status'] == 'BLOCKED'


def test_recovery_restores_production_checks(tmp_path):
    plan = m.Plan('2026-11-03')
    clock = m.SimClock(plan.start)
    def recover():
        if clock.now() < plan.open + timedelta(minutes=1):
            absent()
        return {'health_status': 200}
    _, _, result, engine = execute(tmp_path, recover, clock)
    rows = engine.records
    assert any(r['status'] == 'LIVE' for r in rows)
    assert all(r['status'] != 'LIVE' for r in rows if r['scheduled_at'] < (plan.open + timedelta(minutes=1)).isoformat())
    assert result['real_rth_samples'] == 0


def test_sleep_jump_accounts_for_all_slots_without_backfill(tmp_path):
    plan = m.Plan('2026-11-03')
    class SleepClock(m.SimClock):
        def until(self, target):
            if target >= plan.open + timedelta(hours=4):
                self.at = plan.deadline + timedelta(hours=3)
            else:
                super().until(target)
    _, reader, result, engine = execute(tmp_path, absent, SleepClock(plan.start))
    assert len(engine.records) == 102
    assert any(r['status'] == 'NOT_EXECUTED' for r in engine.records)
    assert result['finalization_status'] == 'LATE_FINALIZED'
    assert not any(t >= plan.deadline for t in reader.calls)
    assert result['real_rth_samples'] == 0


def test_absent_evidence_never_passes(tmp_path):
    _, _, result, _ = execute(tmp_path, absent)
    assert result['items']['版本与端口']['status'] != 'PASS'
    assert result['items']['双窗口横竖屏']['status'] != 'PASS'
    assert 'browser.jsonl' not in result.get('evidence_files', [])


def test_microsecond_boundary_does_not_skip_five_minute_slot(tmp_path):
    plan = m.Plan('2026-11-03')
    class JitterClock(m.SimClock):
        def until(self, target):
            self.at = target + timedelta(microseconds=500 if target.minute % 10 == 0 else 100)
    clock = JitterClock(plan.start)
    calls = []
    def fail():
        calls.append(clock.now())
        absent()
    execute(tmp_path, fail, clock)
    regular = [t for t in calls if plan.open + timedelta(minutes=10) <= t <= plan.close]
    assert max((b-a).total_seconds() for a,b in zip(regular,regular[1:])) < 301


def test_all_planned_slots_have_unique_coverage(tmp_path):
    _, _, result, engine = execute(tmp_path, absent)
    assert len(engine.records) == 102
    assert [r['index'] for r in engine.records] == list(range(102))
    assert result['ict_realtime'] is False


def test_windows_listener_table_does_not_drop_state_zero(monkeypatch):
    class API:
        def __call__(self, buffer, size, order, family, table, reserved):
            assert table == 3  # Windows OWNER_PID_LISTENER表，不是自行猜测State。
            raw = struct.pack('<7I', 1, 0, 0, socket.htons(8501), 0, 0, 12345)
            size._obj.value = len(raw)
            if buffer is None: return 122
            ctypes.memmove(buffer, raw, len(raw))
            return 0
    dll = type('DLL', (), {})(); dll.GetExtendedTcpTable = API()
    monkeypatch.setattr(ctypes, 'WinDLL', lambda _: dll)
    assert m.listeners(8501)[0]['pid'] == 12345
    assert m.listeners(8506) == []


def test_opend_claim_without_worker_trace_cannot_pass(tmp_path):
    plan = m.Plan('2026-11-03')
    engine = m.Controller(plan, tmp_path, None, m.SimClock(plan.close), None, None)
    engine.records = [dict(index=0, scheduled_at=plan.start.isoformat(), status='MISSING', response={
        'opend':'CONNECTED', 'worker_pid':123, 'request_id':'missing', 'state':{'qot_logined':True}})]
    result = engine.finish()
    assert result['items']['独立OpenD连接']['status'] != 'PASS'


def test_original_real_run_reaudit_retains_69_attempts_and_33_unexecuted(tmp_path):
    source = m.ROOT / 'data/live_rth_acceptance/20261103'
    before = {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}
    result = m.audit_existing(source, tmp_path)
    assert result['attempt_count'] == 69 and result['not_executed_count'] == 33
    assert result['coverage_count'] == 102 and result['real_rth_samples'] == 0
    assert result['finalization_status'] == 'LATE_FINALIZED'
    assert result['items']['版本与端口']['status'] == 'BLOCKED'
    assert result['items']['独立OpenD连接']['status'] == 'NOT_OBSERVED'
    assert before == {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()}


def test_unknown_service_stays_fail_closed_while_probe_is_independent(tmp_path):
    def unknown(): raise RuntimeError('UNKNOWN_PID')
    _, reader, result, engine = execute(tmp_path, unknown)
    assert reader.calls and result['items']['版本与端口']['status'] == 'FAIL'
    assert all(r['status'] != 'LIVE' for r in engine.records)


def test_user_tables_and_old_reports_preserved():
    root = m.ROOT
    snapshot = json.loads((root / 'data/rth_recovery_v3/20261104/preservation-before.json').read_text(encoding='utf-8'))
    assert all(hashlib.sha256((root/name).read_bytes()).hexdigest() == digest for name,digest in snapshot['files'].items())
    import sqlite3
    with sqlite3.connect((root/'data/desk.sqlite3').as_uri()+'?mode=ro', uri=True) as db:
        for table, expected in snapshot['user_tables'].items():
            rows = db.execute('SELECT * FROM '+table+' ORDER BY rowid').fetchall()
            assert hashlib.sha256(json.dumps(rows).encode()).hexdigest() == expected['sha256']
