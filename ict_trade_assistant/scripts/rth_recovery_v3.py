"""RTH运行审计修复：独立行情诊断、全计划覆盖、证据驱动裁决；不注册任务。"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

# 正式产品根目录固定；发布工作树不能成为产品运行目录。
ROOT = Path('C:/Users/cbcbe/TradingCodex/ict_trade_assistant')
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'scripts'))
import rth_recovery_v2 as v2
Plan, SimClock, RealClock = v2.Plan, v2.SimClock, v2.RealClock
Reader, SimulationReader = v2.Reader, v2.SimulationReader
TemporaryServiceError = v2.TemporaryServiceError
VERSION = 'RTH_RECOVERY_V3_20261104'


def verify_dependencies():
    manifest = json.loads((ROOT / 'scripts/rth_recovery_v2_manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('ACCEPTANCE_VERSION_DRIFT')
    return manifest


def listeners(port):
    """直接读取Windows IPv4 TCP/PID表，避免CIM State枚举过滤丢失监听行。"""
    class Row(ctypes.Structure):
        _fields_ = [(k, wintypes.DWORD) for k in ('state', 'local_address', 'local_port', 'remote_address', 'remote_port', 'pid')]
    api = ctypes.WinDLL('iphlpapi').GetExtendedTcpTable
    api.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG, ctypes.c_int, wintypes.ULONG]
    api.restype = wintypes.DWORD
    size = wintypes.DWORD()
    # 直接请求OWNER_PID_LISTENER表。本机监听行的原始State为0，不能再以State==2过滤。
    code = api(None, ctypes.byref(size), False, socket.AF_INET, 3, 0)
    if code not in (0, 122):
        raise OSError(code, 'TCP_TABLE_SIZE_FAILED')
    for _ in range(3):
        buffer = ctypes.create_string_buffer(size.value)
        code = api(buffer, ctypes.byref(size), False, socket.AF_INET, 3, 0)
        if code == 122:
            continue
        if code:
            raise OSError(code, 'TCP_TABLE_FAILED')
        count = wintypes.DWORD.from_buffer_copy(buffer).value
        rows = (Row * count).from_buffer_copy(buffer.raw[4:4 + count * ctypes.sizeof(Row)])
        return [dict(pid=r.pid, port=port, native_state=r.state, proof='TCP_TABLE_OWNER_PID_LISTENER') for r in rows
                if socket.ntohs(r.local_port & 65535) == port]
    raise OSError('TCP_TABLE_CHANGED_REPEATEDLY')


def service_identity():
    if not v2.frozen.product_identity()['qualified']:
        raise RuntimeError('FROZEN_DISK_MISMATCH')
    found = listeners(8501)
    if not found:
        raise TemporaryServiceError('SERVICE_ABSENT_NO_AUTOSTART')
    if len(found) != 1:
        raise RuntimeError('MULTIPLE_LISTENERS_FAIL_CLOSED')
    pid = found[0]['pid']
    # 仅输出路径、归属布尔值，不保存未知程序命令行或任何凭据。
    info = v2.frozen.shell("$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(pid) + "';"
        "$pp=Get-CimInstance Win32_Process -Filter ('ProcessId='+$p.ParentProcessId);"
        "@{pid=$p.ProcessId;parent=$p.ParentProcessId;exe=$p.ExecutablePath;parent_exe=$pp.ExecutablePath;"
        "entry=($p.CommandLine -like '*scripts/run_server.py*');parent_entry=($pp.CommandLine -like '*scripts/run_server.py*')}|ConvertTo-Json -Compress")
    runtime = json.loads((ROOT / 'data/runtime.json').read_text())
    owned = (str(info.get('parent_exe', '')).lower() == str(ROOT / '.venv/Scripts/python.exe').lower()
             and info.get('entry') and info.get('parent_entry'))
    result = dict(listeners=found, process=info, runtime=runtime, owned=bool(owned))
    if not (owned and runtime.get('pid') == pid and runtime.get('port') == 8501
            and runtime.get('build_sha256') == v2.frozen.BUILD and Path(runtime.get('root', '')) == ROOT):
        raise v2.frozen.IdentityError('SERVICE_IDENTITY_FAIL_CLOSED', result)
    if not -5 <= time.time() - runtime['at'] <= 30:
        raise TemporaryServiceError('OWN_SERVICE_HEARTBEAT_UNAVAILABLE')
    try:
        with urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3) as response:
            result['health_status'] = response.status
    except OSError as exc:
        raise TemporaryServiceError('OWN_SERVICE_HEALTH_UNAVAILABLE') from exc
    if result['health_status'] != 200:
        raise TemporaryServiceError('OWN_SERVICE_HEALTH_NOT_200')
    return result


def restore_service(output):
    """仅端口空闲且冻结磁盘合格时启动既有入口；不终止任何已有服务。"""
    if listeners(8501):
        return service_identity()
    if not v2.frozen.product_identity()['qualified']:
        raise RuntimeError('FROZEN_DISK_MISMATCH')
    with (Path(output) / 'service-stdout.log').open('ab') as stdout, (Path(output) / 'service-stderr.log').open('ab') as stderr:
        child = subprocess.Popen([str(ROOT / '.venv/Scripts/python.exe'), 'scripts/run_server.py'],
            cwd=ROOT, stdout=stdout, stderr=stderr, creationflags=v2.FLAGS)
    v2.write(Path(output) / 'service-start.json', dict(pid=child.pid, at=v2.utcnow(), entry='scripts/run_server.py', root=str(ROOT)))
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError('OWN_SERVICE_EXITED_' + str(child.returncode))
        try:
            return service_identity()
        except (TemporaryServiceError, OSError, ValueError):
            time.sleep(.5)
    raise RuntimeError('OWN_SERVICE_START_TIMEOUT')


class Controller:
    def __init__(self, plan, output, reader, clock, guard, view, simulated=False):
        self.plan, self.output, self.reader, self.clock = plan, Path(output), reader, clock
        self.guard, self.view, self.simulated = guard, view, simulated
        self.output.mkdir(parents=True, exist_ok=True)
        self.records = []; self.next_check = plan.start; self.integrity_failed = False
        self.blocked = False; self.began = clock.now(); self.pid = os.getpid()
        self.browser = None; self.browser_log = None
        self.lifecycle = dict(version=VERSION, controller_pid=self.pid, actual_started_at=self.began.isoformat(),
            simulated=simulated, deadline=plan.deadline.isoformat(), unattended_conditions='BLOCKED_AWAKE_NOT_GUARANTEED')
        v2.write(self.output / 'lifecycle.json', self.lifecycle)

    def maybe_browser(self):
        if self.simulated or self.browser is not None:
            return
        manifest = verify_dependencies()
        self.browser_log = (self.output / 'browser-process.log').open('ab')
        self.browser = subprocess.Popen([manifest['node'], str(ROOT / 'scripts/rth_browser_recovery_v2.cjs'), str(self.output),
            str(self.plan.deadline.timestamp()), manifest['playwright_module'], manifest['browser_executable'], str(self.plan.open.timestamp())],
            cwd=ROOT, stdout=self.browser_log, stderr=self.browser_log, creationflags=v2.FLAGS)

    def run(self):
        try:
            return self._run()
        finally:
            self.reader.close() if hasattr(self.reader, 'close') else None
            if self.browser and self.browser.poll() is None:
                (self.output / 'STOP').write_text('观察结束', encoding='utf-8')
                try: self.browser.wait(timeout=15)
                except subprocess.TimeoutExpired: self.browser.terminate(); self.browser.wait(timeout=5)
            if self.browser_log: self.browser_log.close()

    def _run(self):
        for index, scheduled in enumerate(self.plan.slots):
            self.clock.until(scheduled); actual = self.clock.now()
            record = dict(index=index, scheduled_at=scheduled.isoformat(), started_at=None, recorded_at=actual.isoformat(),
                simulated=self.simulated, status='NOT_EXECUTED', source=None, response=None, signal_status='UNKNOWN', ict_realtime=False,
                time_contract=v2.qualification(), actual_runtime_pid=None, actual_runtime_fingerprint=None)
            if actual >= self.plan.deadline or (actual - scheduled).total_seconds() > 45:
                record['reason'] = 'DEADLINE_PASSED' if actual >= self.plan.deadline else 'MISSED_DURING_TIME_GAP'
                record['gap_start'] = scheduled.isoformat(); record['gap_end'] = actual.isoformat()
            else:
                record.update(started_at=actual.isoformat(), status='MISSING')
                if actual + timedelta(milliseconds=1) < self.next_check:
                    record['error_category'] = 'RECOVERY_COOLDOWN'
                else:
                    ready = False
                    if not self.integrity_failed:
                        try:
                            record['identity'] = self.guard(); ready = record['identity'].get('health_status') == 200
                            record['service_status'] = 'PASS' if ready else 'BLOCKED'
                            if not ready: record['error_category'] = 'SERVICE_NOT_VERIFIED'
                        except (TemporaryServiceError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
                            record.update(service_status='BLOCKED', error_category='SERVICE_UNAVAILABLE_NO_TAKEOVER', reason=str(exc))
                        except Exception as exc:
                            self.integrity_failed = True
                            record.update(service_status='FAIL', error_category='SERVICE_IDENTITY_FAIL_CLOSED', reason=type(exc).__name__)
                    # 独立诊断只做preflight；无生产服务时绝不把探针报价变成LIVE。
                    command = 'quotes' if ready and self.plan.rth(actual) else 'preflight'
                    try:
                        record['response'] = self.reader.read(command, actual)
                        record['source'] = 'SIMULATED_ENGINEERING_ONLY' if self.simulated else 'FUTU_OPEND'
                        record['probe_scope'] = 'PRODUCTION_SERVICE_VERIFIED' if ready else 'INDEPENDENT_DIAGNOSTIC_ONLY'
                        valid = v2.valid_quotes(record['response'], self.clock.now(), self.plan) if ready else {}
                        record['qualified_quotes'] = valid
                        if ready and len(valid) == len(v2.SYMBOLS):
                            record['status'] = 'LIVE'
                            if self.blocked: record['recovered_at'] = self.clock.now().isoformat()
                            self.blocked = False
                        elif ready and not record['response'].get('error'):
                            record['status'] = 'PRECHECK_OK' if not self.plan.rth(actual) else 'DATA_UNQUALIFIED'
                        if record['response'].get('error'):
                            record['diagnostic_error'] = record['response'].get('category', 'UNKNOWN_ERROR')
                    except Exception as exc:
                        record['diagnostic_error'] = type(exc).__name__
                    if record['status'] in ('MISSING', 'DATA_UNQUALIFIED'):
                        self.blocked = True
                        self.next_check = actual + timedelta(seconds=self.plan.retry_seconds(actual))
                    if ready:
                        try: self.maybe_browser()
                        except Exception as exc: record['browser_start_error'] = type(exc).__name__
                try: record['view'] = self.view()
                except Exception as exc: record['view_error'] = type(exc).__name__
                record['completed_at'] = self.clock.now().isoformat()
                identity = record.get('identity', {})
                if identity.get('health_status') == 200:
                    record['actual_runtime_pid'] = identity.get('runtime', {}).get('pid')
                    record['actual_runtime_fingerprint'] = identity.get('runtime', {}).get('build_sha256')
                v2.append(self.output / 'attempts.jsonl', record)
            self.records.append(record)
            v2.write(self.output / 'checkpoint.json', dict(index=index, status=record['status'], at=self.clock.now()))
        return self.finish()

    def finish(self):
        live = [r for r in self.records if r['status'] == 'LIVE']
        advancing = {s:len({r.get('qualified_quotes', {}).get(s, {}).get('quote_at') for r in live}) for s in v2.SYMBOLS}
        service = [r.get('identity', {}) for r in self.records if r.get('identity', {}).get('health_status') == 200]
        phases = []
        for path in (self.output / 'workers').glob('*/phases.jsonl'):
            phases.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())
        def connected_evidence(record):
            response = record.get('response') or {}
            if response.get('opend') != 'CONNECTED': return False
            if self.simulated: return True
            observed = {p['phase'] for p in phases if p.get('pid') == response.get('worker_pid')
                        and p.get('request_id') == response.get('request_id')}
            return {'GLOBAL_STATE_REQUEST','RESPONSE_COMPLETE'} <= observed and response.get('state', {}).get('qot_logined') is True
        connected = [r for r in self.records if connected_evidence(r)]
        late = self.clock.now() > self.plan.deadline
        unexecuted = [r for r in self.records if r['status'] == 'NOT_EXECUTED']
        views = [r['view'] for r in self.records if r.get('view')]
        browser_path = self.output / 'browser.jsonl'
        browser = [json.loads(line) for line in browser_path.read_text(encoding='utf-8').splitlines()] if browser_path.exists() else []
        good = [b for b in browser if b.get('ok') and self.plan.rth(datetime.fromisoformat(b['at']))]
        items = {'版本与端口':dict(status='FAIL' if self.integrity_failed else 'PASS' if service else 'BLOCKED', successful_checks=len(service)),
            '独立OpenD连接':dict(status='PASS' if connected else 'NOT_OBSERVED', successful_checks=len(connected), scope='独立行情诊断，不代表生产验收'),
            '四ETF新报价推进':dict(status='PASS' if all(n >= 2 for n in advancing.values()) else 'BLOCKED', distinct_timestamps=advancing),
            '双窗口横竖屏':dict(status='PASS' if {b.get('symbol') for b in good} == {'SPY','QQQ'} else 'BLOCKED', checks=len(good)),
            '分钟契约':dict(status='BLOCKED', reason='TIME_CONTRACT_UNRESOLVED'),
            'ICT实时事件':dict(status='BLOCKED', reason='UNKNOWN；实时提醒关闭'),
            'ICT提醒页面锁定':dict(status='FAIL' if any(b.get('liveViolation') for b in browser) else 'PASS' if good else 'NOT_OBSERVED'),
            '用户记录保持':dict(status='PASS' if views and all(v.get('protected') == views[0].get('protected') for v in views) else 'NOT_OBSERVED')}
        items['90秒门禁'] = dict(status='PASS' if live else 'NOT_OBSERVED', qualified_groups=len(live), gate_seconds=90)
        for label in ('市场触价与提醒去重','候选距离变化','自然断线与产品恢复','LIVE/PREPARATION切换','Top5同期证券去重'):
            items[label] = dict(status='NOT_OBSERVED', reason='保留原始样本；没有独立完整证据时不授予通过')
        items['首小时1H资格'] = dict(status='BLOCKED', reason='TIME_CONTRACT_UNRESOLVED；两分钟隔离不变')
        v2.write(self.output / 'coverage.json', [dict(index=r['index'], scheduled_at=r['scheduled_at'], status=r['status'],
            started_at=r.get('started_at'), completed_at=r.get('completed_at'), reason=r.get('reason', r.get('error_category'))) for r in self.records])
        v2.write(self.output / 'gaps.json', [r for r in self.records if r['status'] in ('MISSING','NOT_EXECUTED')])
        self.lifecycle.update(actual_completed_at=self.clock.now().isoformat(), finalization_status='LATE_FINALIZED' if late else 'ON_TIME',
            last_sample_completed_at=next((r.get('completed_at') for r in reversed(self.records) if r.get('completed_at')), None))
        v2.write(self.output / 'lifecycle.json', self.lifecycle)
        result = dict(version=VERSION, simulated=self.simulated, date=self.plan.day, status='BLOCKED' if unexecuted or not live else 'PARTIAL_EVIDENCE',
            finalization_status=self.lifecycle['finalization_status'], planned_count=len(self.plan.slots), coverage_count=len(self.records),
            attempt_count=sum(r['status'] != 'NOT_EXECUTED' for r in self.records), not_executed_count=len(unexecuted),
            real_rth_samples=0 if self.simulated else len(live), simulated_qualified_groups=len(live) if self.simulated else 0,
            worker_starts=getattr(self.reader, 'starts', None), items=items, ict_realtime=False,
            evidence_files=sorted(p.relative_to(self.output).as_posix() for p in self.output.rglob('*') if p.is_file()), exit_code=2 if unexecuted or not live else 0)
        v2.write(self.output / 'SUMMARY.json', result)
        lines = ['# RTH运行审计修复v3', '', '【执行状态】'+result['status']+'；'+result['finalization_status'],
            f'【计划覆盖】{len(self.records)}/{len(self.plan.slots)}；实际执行{result["attempt_count"]}；未执行{len(unexecuted)}。',
            '【证据边界】模拟仅为工程验证；独立探针不代表生产LIVE；历史缺口不回填。', '', '| 项目 | 裁定 |', '|---|---|']
        lines += ['| '+k+' | '+v['status']+' |' for k,v in items.items()]
        lines += ['', '【实际证据文件】'] + ['- '+p for p in result['evidence_files']]
        lines += ['', '【无人值守条件】当前唤醒条件未获保证；不能保证睡眠期间执行或截止落盘。未修改电源/安全配置。',
            '【下一步】保持ICT关闭；本程序没有注册任务。']
        (self.output / 'FINAL_REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        return result


def audit_existing(source, output):
    """原报告只读，新裁决另存；不请求行情、不重新执行历史任务。"""
    old = json.loads((source / 'SUMMARY.json').read_text(encoding='utf-8'))
    plan = Plan(old['date']); clock = SimClock(datetime.fromisoformat(old['completed_at']))
    engine = Controller(plan, output, None, clock, None, None)
    engine.lifecycle['controller_pid'] = None
    engine.lifecycle['audit_pid'] = os.getpid()
    engine.lifecycle['audit_generated_at'] = v2.utcnow().isoformat()
    engine.lifecycle['actual_started_at'] = None
    rows = {r['index']:r for r in [json.loads(s) for s in (source / 'attempts.jsonl').read_text(encoding='utf-8').splitlines()]}
    engine.records = [rows.get(i, dict(index=i, scheduled_at=t.isoformat(), status='NOT_EXECUTED', started_at=None,
        reason='ORIGINAL_RUN_NO_RECORD', response=None, ict_realtime=False)) for i,t in enumerate(plan.slots)]
    v2.write(output / 'source-hashes.json', {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()})
    return engine.finish()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    action = p.add_mutually_exclusive_group(required=True)
    action.add_argument('--restore-service', action='store_true'); action.add_argument('--diagnose', action='store_true')
    action.add_argument('--audit-existing', type=Path); action.add_argument('--observe', action='store_true')
    p.add_argument('--output', type=Path, required=True); p.add_argument('--date'); p.add_argument('--acknowledge-session-required', action='store_true')
    args = p.parse_args(); verify_dependencies(); args.output.mkdir(parents=True, exist_ok=False)
    if args.restore_service:
        v2.write(args.output / 'service-identity.json', restore_service(args.output)); return 0
    if args.diagnose:
        reader = Reader(args.output)
        try:
            result = reader.read('preflight', v2.utcnow())
            result['scope'] = 'INDEPENDENT_DIAGNOSTIC_ONLY'; result['real_rth_samples'] = 0
            v2.write(args.output / 'diagnostic.json', result)
            return 2 if result.get('error') else 0
        finally: reader.close()
    if args.audit_existing:
        audit_existing(args.audit_existing, args.output); return 0
    if not args.acknowledge_session_required:
        p.error('无人值守唤醒条件未保证，必须明确确认当前会话运行条件；本入口不注册任务')
    plan = Plan(args.date)
    if not plan.start - timedelta(minutes=2) <= v2.utcnow() <= plan.deadline:
        p.error('OUTSIDE_RTH_OBSERVATION_WINDOW')
    lock = v2.frozen.acquire_lock(args.output / 'run.lock')
    try:
        result = Controller(plan, args.output, Reader(args.output), RealClock(), service_identity, v2.readonly_market_view).run()
        return result['exit_code']
    finally: lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
