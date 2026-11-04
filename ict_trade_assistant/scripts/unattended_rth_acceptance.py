"""20261102 一次性只读验收。独立于冻结产品，不修改 SQLite 或策略。"""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
ET = ZoneInfo('America/New_York')
HK = ZoneInfo('Asia/Hong_Kong')
START = datetime(2026, 11, 2, 22, 15, tzinfo=HK)
OPEN = datetime(2026, 11, 2, 9, 30, tzinfo=ET)
CLOSE = OPEN.replace(hour=16, minute=0)
END = datetime(2026, 11, 3, 5, 8, tzinfo=HK)  # 给05:10硬截止留两分钟落盘
BASE = '92ce0a2f8c371dbea742ac2c5c92228be72d53e0'
BUILD = '19d76ebe4792b5ce894f9826e338b752dd05d3d8416500798ef30ac40e9ea329'
OUT = ROOT / 'data/live_rth_acceptance/20261102'
SYMBOLS = ('US.SPY', 'US.QQQ', 'US.IWM', 'US.SOXX')
VERDICTS = {'PASS', 'FAIL', 'BLOCKED', 'PENDING_NO_NATURAL_EVENT', 'NOT_OBSERVED'}
FLAGS = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


class IdentityError(RuntimeError):
    def __init__(self, code, details):
        super().__init__(code)
        self.details = details


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    temp.replace(path)


def append(path, value):
    with Path(path).open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False, default=str) + '\n')


def now():
    return datetime.now(ET)


def shell(code, timeout=15):
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', code],
                            cwd=ROOT, capture_output=True, timeout=timeout, creationflags=FLAGS)
    if result.returncode:
        raise RuntimeError('WINDOWS_API_FAILED_' + str(result.returncode))
    return json.loads(result.stdout.decode('utf-8-sig'))


def product_identity():
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, creationflags=FLAGS).decode().strip()
    clean = subprocess.run(['git', 'diff', '--quiet', BASE, '--'], cwd=ROOT, creationflags=FLAGS).returncode == 0
    sources = [ROOT/'app.py', ROOT/'scripts/run_server.py'] + sorted((ROOT/'desk').glob('*.py'))
    digest = hashlib.sha256(b''.join(p.read_bytes() for p in sources)).hexdigest()
    return dict(head=head, tracked_baseline_unchanged=clean, build_sha256=digest,
                qualified=head == BASE and clean and digest == BUILD)


def service_identity(start_if_absent=False):
    from urllib.request import urlopen
    probe = "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new(); "
    probe += "$ls=@(Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue); "
    probe += "$ps=@(); foreach($l in $ls){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$l.OwningProcess); "
    probe += "$pp=Get-CimInstance Win32_Process -Filter ('ProcessId='+$p.ParentProcessId); "
    probe += "$ps+=@{pid=$p.ProcessId;parent=$p.ParentProcessId;exe=$p.ExecutablePath;command=$p.CommandLine;parent_exe=$pp.ExecutablePath;parent_command=$pp.CommandLine}}; "
    probe += "@{listeners=$ps}|ConvertTo-Json -Compress -Depth 4"
    info = shell(probe)
    listeners = info['listeners']
    if not listeners and start_if_absent:
        # 新启动也必须先验证磁盘；只启动本项目，不停止任何进程。
        if not product_identity()['qualified']:
            raise RuntimeError('DISK_VERSION_MISMATCH')
        log = (OUT/'service-start.log').open('ab')
        try:
            proc = subprocess.Popen([str(ROOT/'.venv/Scripts/python.exe'), 'scripts/run_server.py'],
                                    cwd=ROOT, stdout=log, stderr=log, creationflags=FLAGS)
        finally:
            log.close()
        for _ in range(30):
            time.sleep(1)
            if proc.poll() is not None:
                raise RuntimeError('OWN_SERVICE_START_EXITED')
            try:
                return service_identity(False)
            except (OSError, ValueError, RuntimeError):
                pass
        raise RuntimeError('OWN_SERVICE_START_TIMEOUT')
    if len(listeners) != 1:
        raise RuntimeError('PORT_ABSENT_OR_MULTIPLE_' + str(len(listeners)))
    runtime = json.loads((ROOT/'data/runtime.json').read_text())
    listener = listeners[0]
    owned = (str(ROOT/'.venv/Scripts/python.exe').lower() == str(listener.get('parent_exe', '')).lower()
             and 'scripts/run_server.py' in (listener.get('command') or '')
             and 'scripts/run_server.py' in (listener.get('parent_command') or ''))
    # 不把未知程序命令行（可能含秘密）写入证据；仅记录哈希与实际PID。
    for value in listeners:
        for key in ('command','parent_command'):
            value[key+'_sha256'] = hashlib.sha256((value.get(key) or '').encode()).hexdigest()
            value.pop(key,None)
    result = dict(**info, runtime=runtime, heartbeat_age=time.time()-runtime['at'], owned=owned)
    if (not owned or runtime['pid'] != listener['pid'] or Path(runtime['root']) != ROOT
            or runtime['port'] != 8501 or runtime['build_sha256'] != BUILD
            or not -5 <= result['heartbeat_age'] <= 30):
        raise IdentityError('PORT_IDENTITY_FAIL_CLOSED', result)
    with urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3) as response:
        result['health_status'] = response.status
    if result['health_status'] != 200:
        raise RuntimeError('HEALTH_NOT_200')
    return result


def readonly_state():
    from desk.store import DEFAULTS
    settings = json.loads(json.dumps(DEFAULTS))
    fingerprints, observations = {}, {}
    with sqlite3.connect((ROOT/'data/desk.sqlite3').as_uri()+'?mode=ro', uri=True, timeout=3) as db:
        db.execute('BEGIN')
        for key, value in db.execute('SELECT key,value FROM settings'):
            if key in settings:
                settings[key] = json.loads(value)
        for table in ('notes', 'plan_versions', 'settings', 'acknowledgements', 'audit'):
            rows = db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            fingerprints[table] = dict(count=len(rows), sha256=hashlib.sha256(json.dumps(rows).encode()).hexdigest())
        for symbol, payload in db.execute('SELECT symbol,payload FROM observation_snapshots'):
            observations[symbol] = json.loads(payload)
        events = [dict(id=r[0], at=r[1], kind=r[2], symbol=r[3], reason=r[4], payload=json.loads(r[5] or '{}'), dedupe=r[6])
                  for r in db.execute('SELECT * FROM events ORDER BY id')]
    return dict(settings=settings, protected=fingerprints, observations=observations, events=events)


def quote_worker(conn):
    """唯一额外行情连接，订阅一次；不请求账户或订单，身份信息不离开进程。"""
    import futu as ft
    from desk.provider import quote_quality
    ctx, subscribed = None, False
    try:
        while True:
            command = conn.recv()
            if command == 'stop':
                break
            if ctx is None:
                ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111)
            received = now()
            ret, state = ctx.get_global_state()
            if ret != ft.RET_OK or state.get('qot_logined') not in (True, 1, '1'):
                conn.send(dict(error='OPEND_QUOTE_NOT_LOGGED_IN', opend='UNAVAILABLE'))
                continue
            ret, user = ctx.get_user_info()
            right = user.get('us_qot_right', 'UNKNOWN') if ret == ft.RET_OK else 'UNKNOWN'
            result = dict(opend='CONNECTED', right=right,
                          state={k:state.get(k) for k in ('qot_logined','timestamp','market_us','program_status_type')},
                          server_skew=float(state['timestamp'])-received.timestamp(), received_at=received.isoformat())
            if command == 'preflight':
                ret, subs = ctx.query_subscription(is_all_conn=True)
                result['subscriptions'] = {k:subs.get(k) for k in ('total_used','remain','own_used','sub_list')} if ret == 0 else None
            elif command == 'first_hour':
                from desk.analytics import normalize
                result['minutes'] = {}
                for symbol in SYMBOLS:
                    ret, frame, key = ctx.request_history_kline(symbol, start='2026-11-02', end='2026-11-02',
                        ktype=ft.KLType.K_1M, autype=ft.AuType.NONE, max_count=1000, session=ft.Session.RTH)
                    result['minutes'][symbol] = dict(pagination_complete=key is None, ret=ret,
                        fetched_at=now().isoformat(), rows=normalize(frame, '1M', now()).to_dict('records') if ret == 0 else [])
            else:
                if not subscribed:
                    ret, _ = ctx.subscribe(list(SYMBOLS), [ft.SubType.QUOTE], subscribe_push=False, session=ft.Session.RTH)
                    if ret != ft.RET_OK:
                        conn.send(dict(error='QUOTE_SUBSCRIPTION_FAILED', **result))
                        continue
                    subscribed = True
                ret, frame = ctx.get_stock_quote(list(SYMBOLS))
                result['quotes'] = {}
                if ret == ft.RET_OK:
                    for _, row in frame.iterrows():
                        result['quotes'][row['code']] = quote_quality(row, right, now(), result['server_skew'])
                else:
                    result['error'] = 'QUOTE_REQUEST_FAILED'
            conn.send(result)
    except (EOFError, BrokenPipeError):
        pass
    except Exception as exc:
        try:
            conn.send(dict(error='QUOTE_WORKER_'+type(exc).__name__, opend='UNKNOWN'))
        except (EOFError, BrokenPipeError):
            pass
    finally:
        if ctx is not None:
            ctx.close()


class QuoteReader:
    def __init__(self):
        self.process, self.conn, self.starts = None, None, 0

    def read(self, command, timeout=20):
        if self.process is None or not self.process.is_alive():
            self.close()
            if self.starts >= 3:
                return dict(error='QUOTE_RECOVERY_LIMIT_3', opend='UNAVAILABLE')
            self.starts += 1
            self.conn, child = mp.Pipe()
            self.process = mp.Process(target=quote_worker, args=(child,), daemon=True)
            self.process.start()
            child.close()
        try:
            self.conn.send(command)
            if not self.conn.poll(timeout):
                self.close()
                return dict(error='QUOTE_TIMEOUT', opend='UNAVAILABLE')
            result = self.conn.recv()
            if result.get('error'):
                self.close()
            return result
        except (OSError, EOFError, BrokenPipeError):
            self.close()
            return dict(error='QUOTE_PIPE_FAILURE', opend='UNAVAILABLE')

    def close(self):
        if self.process is not None:
            if self.process.is_alive():
                try:
                    self.conn.send('stop')
                except (OSError, BrokenPipeError):
                    pass
                self.process.join(1)
            if self.process.is_alive():
                self.process.terminate()  # 仅本验收程序创建的行情子进程
                self.process.join(3)
            self.process = None
        if self.conn is not None:
            self.conn.close()
            self.conn = None


def schedule():
    """预检、开盘前、开盘后5分钟每15秒、之后每5分钟、首小时、收盘后。"""
    ticks = {START, OPEN-timedelta(seconds=15), CLOSE+timedelta(seconds=15)}
    ticks.update(OPEN+timedelta(seconds=i) for i in range(0, 301, 15))
    ticks.update(OPEN+timedelta(minutes=i) for i in range(10, 391, 5))
    ticks.add(OPEN+timedelta(hours=1, minutes=2))
    return sorted(ticks)


class Audit:
    def __init__(self, output, simulated=False):
        self.output, self.simulated = Path(output), simulated
        self.output.mkdir(parents=True, exist_ok=True)
        self.items, self.samples, self.errors = {}, [], []
        self.last_good = {}

    def verdict(self, key, status, evidence):
        assert status in VERDICTS
        # 已证实失败不可被后续健康样本覆盖。
        if self.items.get(key, {}).get('status') == 'FAIL' and status != 'FAIL':
            return
        self.items[key] = dict(status=status, evidence=evidence)

    def error(self, code, at, service=None, quote=None):
        listeners=(service or {}).get('listeners', [])
        value = dict(at=at, code=code, actual_pid=listeners[0]['pid'] if listeners else None,
                     actual_fingerprint=(service or {}).get('runtime', {}).get('build_sha256'),
                     opend=(quote or {}).get('opend', 'UNKNOWN'), last_qualified_quote=self.last_good.copy(),
                     completed=[k for k,v in self.items.items() if v['status']=='PASS'],
                     remaining=[k for k,v in self.items.items() if v['status']!='PASS'])
        self.errors.append(value)
        append(self.output/'errors.jsonl', value)

    def sample(self, at, identity, quote, state):
        from desk.observations import ranked, regions
        obs = {k:v for k,v in state['observations'].items() if k in SYMBOLS}
        rows = ranked(obs)
        item = dict(at=at.isoformat(), simulated=self.simulated, identity=identity, quote=quote,
                    observations=obs, top5=rows[:5], regions={k:regions(v) for k,v in obs.items()},
                    protected=state['protected'], events=state['events'])
        # 完整每组证据逐组落盘；报告中只保留索引，避免内存随事件表增长。
        append(self.output/'samples.jsonl', item)
        self.samples.append(item)
        self.verdict('版本归属', 'PASS', '每组磁盘、8501 PID/归属/心跳/健康接口均核验')
        for symbol, health in quote.get('quotes', {}).items():
            if health.get('quality') == 'AVAILABLE':
                self.last_good[symbol] = health.get('quote_at')
        unique = len({r['symbol'] for r in rows[:5]}) == len(rows[:5]) and len(rows[:5]) <= 4
        self.verdict('证券去重和区域聚合', 'FAIL' if not unique else 'PASS' if rows else 'NOT_OBSERVED', '真实观察快照按冻结regions/ranked重新计算；每组保存全部原始价位和聚合区间，空候选不冒充通过')
        duplicates = [e['dedupe'] for e in state['events'] if e['dedupe']]
        if len(duplicates) != len(set(duplicates)):
            self.verdict('市场事件去重', 'FAIL', '实际事件表出现重复dedupe')

    def finish(self, blocked=None):
        from desk.clock import session
        rth = [s for s in self.samples if session(datetime.fromisoformat(s['at']).astimezone(ET)) == 'RTH']
        qualified = {s:[] for s in SYMBOLS}
        for sample in rth:
            for symbol in SYMBOLS:
                h = sample['quote'].get('quotes', {}).get(symbol, {})
                if h.get('quality') == 'AVAILABLE':
                    qualified[symbol].append(h['quote_at'])
        advancing = all(len(set(v)) >= 2 for v in qualified.values())
        self.verdict('四ETF新报价', 'PASS' if advancing else 'BLOCKED', {s:len(set(v)) for s,v in qualified.items()})
        rights=sorted({s['quote'].get('right','UNKNOWN') for s in self.samples})
        self.verdict('实际行情权限', 'PASS' if any(x in ('LV1','LV2','LV3') for x in rights) else 'BLOCKED',
                     dict(observed=rights, note='仅核实现有权限，不切换或升级权限；权限不等于新报价资格'))
        available = [h for s in rth for h in s['quote'].get('quotes',{}).values() if h.get('quality')=='AVAILABLE']
        safe = all(-5 <= h['age_seconds'] <= 90 and abs(h['server_clock_skew_seconds']) <= 5
                   and h['right'] in ('LV1','LV2','LV3') for h in available)
        stale = [h for s in rth for h in s['quote'].get('quotes',{}).values() if h.get('quality')=='STALE']
        self.verdict('90秒门禁', 'FAIL' if not safe else 'PASS' if available else 'BLOCKED',
                     dict(qualified=len(available), naturally_stale=len(stale), note='无自然过期时只证明实际合格报价安全，过期分支另列'))
        modes = {o['mode'] for s in self.samples for o in s['observations'].values()}
        self.verdict('PREPARATION与LIVE切换', 'PASS' if {'PREPARATION','LIVE'} <= modes else 'NOT_OBSERVED', sorted(modes))
        changed, transitions, matched_events, gap_violations = [], [], [], []
        previous = {}
        for sample in self.samples:
            for symbol, observation in sample['observations'].items():
                if observation.get('mode') != 'LIVE' or observation.get('status') != 'AVAILABLE':
                    continue
                for row in observation.get('monitors', []):
                    row_at=datetime.fromisoformat(row['quote_at'])
                    if not -5 <= (datetime.fromisoformat(sample['at'])-row_at).total_seconds() <= 90:
                        continue  # 持久快照不等于此刻仍合资格；不以旧数据证明实时距离
                    identity = (symbol,row['key'],row['low'],row['high'],row.get('parameter_version'),row.get('trading_day'))
                    price, low, high, atr = row['price'],row['low'],row['high'],row['atr']
                    expected = max(low-price,price-high,0)
                    if abs(row['gap']-expected)>1e-7 or abs(row['atr_distance']-expected/atr)>1e-7:
                        gap_violations.append(identity)
                    old = previous.get(identity)
                    if old and row['quote_at'] > old['quote_at']:
                        if row['price'] != old['price'] and row['gap'] != old['gap']:
                            changed.append(dict(symbol=symbol,key=row['key'],before=old,after=row))
                        if row['state'] != old['state']:
                            transitions.append(dict(symbol=symbol,key=row['key'],before=old,after=row))
                    previous[identity] = row
        all_events = self.samples[-1]['events'] if self.samples else []
        first_id = max((e['id'] for e in self.samples[0]['events']), default=0) if self.samples else 0
        new_events = [e for e in all_events if e['id'] > first_id]
        market_events = [e for e in new_events if e['kind']=='MARKET_OBSERVATION']
        for change in transitions:
            row = change['after']
            matches = [e for e in market_events if e['symbol']==row['symbol'] and e['payload'].get('key')==row['key']
                       and e['payload'].get('quote_at')==row['quote_at'] and e['payload'].get('state')==row['state']]
            matched_events.append(dict(change=change,event_ids=[e['id'] for e in matches]))
        self.verdict('候选距离', 'FAIL' if gap_violations else 'PASS' if changed else 'NOT_OBSERVED',
                     dict(changes=len(changed), formula_failures=gap_violations))
        self.verdict('自然状态转换', 'PASS' if transitions else 'PENDING_NO_NATURAL_EVENT', dict(count=len(transitions)))
        duplicate_natural = any(len(m['event_ids'])>1 for m in matched_events)
        exact_match = bool(matched_events) and all(len(m['event_ids'])==1 for m in matched_events)
        self.verdict('市场事件去重', 'FAIL' if duplicate_natural else 'PASS' if exact_match else 'NOT_OBSERVED',
                     dict(market_event_ids=[e['id'] for e in market_events],matched=matched_events))
        disconnected=[s['at'] for s in self.samples if s['quote'].get('error')]
        self.verdict('自然断线与有限恢复', 'NOT_OBSERVED' if disconnected else 'PENDING_NO_NATURAL_EVENT',
                     dict(disconnections=disconnected, note='不主动断线；部分断线不等于已验证产品恢复链；错误、页面诊断完整留证'))
        stale_product=[]
        for sample in rth:
            for symbol, health in sample['quote'].get('quotes',{}).items():
                if health.get('quality')=='STALE':
                    observed=sample['observations'].get(symbol,{})
                    stale_product.append(observed.get('mode')=='HISTORICAL_ONLY')
        self.verdict('自然数据过期安全降级', 'PASS' if stale_product and all(stale_product) else 'NOT_OBSERVED' if stale else 'PENDING_NO_NATURAL_EVENT',
                     dict(stale_quotes=len(stale), product_blocking_snapshots=sum(stale_product),
                          note='额外报价连接的STALE不能单独证明生产看板已降级；须同时取得生产HISTORICAL_ONLY快照'))
        self.verdict('持久化备注保存', 'BLOCKED', '生产库禁止提交；只读核对指纹，隔离库工程测试不充当生产验收')
        self.verdict('ICT实时结构资格', 'BLOCKED', 'PENDING_ICT_REALTIME：供应商最终性及原始分钟到达时点未证明；不要求自然结构出现')
        self.verdict('首根1H', self.items.get('首根1H',{}).get('status','NOT_OBSERVED'),
                     self.items.get('首根1H',{}).get('evidence','尚未到达10:32或未取得分钟证据'))
        browser = []
        path = self.output/'browser.jsonl'
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:browser.append(json.loads(line))
                except ValueError:pass
        eligible_browser=browser if self.simulated else [b for b in browser if OPEN <= datetime.fromisoformat(b['at']) < CLOSE]
        good = [b for b in eligible_browser if b.get('ok')]
        bad = [b for b in browser if not b.get('ok')]
        self.verdict('双窗口与横竖屏', 'FAIL' if bad else 'PASS' if good else 'BLOCKED', dict(success=len(good),failures=len(bad)))
        self.verdict('窗口选择与自动刷新', 'FAIL' if bad else 'PASS' if any(b.get('refreshProven') for b in good) else 'NOT_OBSERVED', '浏览器页面时钟推进，选股持续一致，未重载页面来冒充自动刷新')
        self.verdict('ICT自动提醒关闭', 'FAIL' if any(b.get('liveViolation') for b in browser) else 'PASS' if good else 'BLOCKED', '两个页面实时ICT复选框持续disabled且unchecked')
        self.verdict('候选与SOP一致', 'FAIL' if any(b.get('candidateViolation') for b in browser) else 'PASS' if any(b.get('candidateChecked') for b in good) else 'NOT_OBSERVED', '只在存在真实候选时点击候选并核对相同证券/区域，不改策略或参数')
        self.verdict('全时段采样覆盖', 'PASS' if len(self.samples)==len(schedule()) else 'BLOCKED',
                     dict(planned_ticks=len(schedule()), actual_samples=len(self.samples), simulated=self.simulated))
        if self.samples:
            equal = self.samples[0]['protected'] == self.samples[-1]['protected']
            self.verdict('用户记录保持', 'PASS' if equal else 'NOT_OBSERVED',
                         '备注、计划、设置、已读、审计只读指纹相同' if equal else '指纹变化；需区分用户正常修改，不能归因为验收写入')
        if blocked:
            self.verdict('自动执行阻断', 'BLOCKED', blocked)
        dump(self.output/'transitions.json', dict(distance_changes=changed, natural_transitions=transitions, events=new_events))
        summary = dict(phase='真实RTH一次性自动验收', simulated=self.simulated,
                       real_live_acceptance='PENDING_LIVE_ACCEPTANCE' if self.simulated else '逐项裁定，无整体通过捷径',
                       completed_at=now().isoformat(), sample_count=len(self.samples), rth_samples=0 if self.simulated else len(rth),
                       simulated_rth_ticks=len(rth) if self.simulated else 0,
                       baseline=BASE, expected_fingerprint=BUILD, items=self.items, errors=self.errors,
                       last_qualified_quote=self.last_good, report=str(self.output/'FINAL_REPORT.md'))
        dump(self.output/'SUMMARY.json', summary)
        lines = ['# 真实RTH无人值守验收报告', '', '【当前阶段】'+('离线模拟／Dry Run，不构成真实盘中证据' if self.simulated else '真实RTH一次性自动验收结束'),
                 '', '【执行状态】'+('BLOCKED：'+blocked if blocked else '采样已停止，逐项结论如下；退出码0不等于整体通过。'),
                 '', '【已完成】保存原始报价、运行身份、生产只读快照、事件ID、浏览器证据及错误记录。',
                 '', '【测试与证据】样本 '+str(len(self.samples))+' 组；真实时钟RTH样本 '+str(0 if self.simulated else len(rth))+' 组。',
                 '', '| 项目 | 裁定 | 证据 |', '|---|---|---|']
        for key, value in self.items.items():
            lines.append('| '+key+' | '+value['status']+' | '+json.dumps(value['evidence'], ensure_ascii=False, default=str).replace('|','／').replace('\n',' ')+' |')
        lines += ['', '【存在问题】模拟数据不构成真实证据；没有自然事件时不强行制造通过；供应商结构资格保持PENDING_ICT_REALTIME。',
                  '', '【下一步】人工审阅逐项证据。实时ICT提醒继续锁定关闭；程序不会停止既有8501，不自动合并或发布。']
        (self.output/'FINAL_REPORT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        return summary


def first_hour(audit, result, at):
    import pandas as pd
    from desk.ict_v03 import _input, _bars, scan
    evidence = {}
    for symbol in SYMBOLS:
        raw = result.get('minutes', {}).get(symbol, {})
        frame = pd.DataFrame(raw.get('rows', []))
        if frame.empty:
            evidence[symbol] = dict(qualified=False, reason='MINUTE_EVIDENCE_MISSING')
            continue
        frame['ts'] = pd.to_datetime(frame.ts, utc=True).dt.tz_convert(ET)
        before = OPEN+timedelta(hours=1, minutes=1, seconds=59)
        boundary = OPEN+timedelta(hours=1, minutes=2)
        bars_before, _ = _bars(_input(frame, before), before)
        bars_after, _ = _bars(_input(frame, boundary), boundary)
        matches = [b for b in bars_after if b['ts']==OPEN and b.get('complete')]
        no_early = not any(b['ts']==OPEN and b.get('complete') for b in bars_before)
        prefix = frame[frame.ts < OPEN+timedelta(hours=1)].copy()
        full_scan = scan(symbol, frame, boundary)
        prefix_scan = scan(symbol, prefix, boundary)
        same = full_scan == prefix_scan
        evidence[symbol] = dict(qualified=len(matches)==1 and no_early and same and raw.get('pagination_complete',False),
            raw_minutes=len(prefix), before_103159_unconfirmed=no_early, prefix_equal=same,
            confirmed_bars=matches, source='FUTU_OPEND / request_history_kline / RTH',
            fetched_at=raw.get('fetched_at'), vendor_finality='UNVERIFIED', first_arrival='UNVERIFIED')
    hour_evidence=dict(at=at, raw=result, checks=evidence)
    append(audit.output/'first-hour-attempts.jsonl', hour_evidence)
    dump(audit.output/'first-hour.json', hour_evidence)
    audit.verdict('首根1H', 'PASS' if all(v['qualified'] for v in evidence.values()) else 'BLOCKED', evidence)


def acquire_lock(path):
    """Windows文件锁自动随进程结束释放；保留锁文件不等于占用。"""
    import msvcrt
    handle = path.open('a+b')
    if handle.tell()==0:
        handle.write(b'0');handle.flush()
    handle.seek(0)
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        raise RuntimeError('ALREADY_RUNNING')
    return handle


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--browser-seconds', type=int, default=0)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.live == args.dry_run:
        parser.error('必须明确选择--live或--dry-run')
    output = args.output or OUT
    if args.dry_run and output == OUT:
        parser.error('Dry Run必须指定独立输出目录，不覆盖正式证据')
    if args.live and (args.output or args.preflight or args.browser_seconds):
        parser.error('正式任务不接受输出重定向或测试时钟选项')
    output.mkdir(parents=True, exist_ok=True)
    if args.live and (output/'SUMMARY.json').exists():
        raise SystemExit('ALREADY_COMPLETED_NO_OVERWRITE')
    lock = acquire_lock(output/'run.lock')
    audit = Audit(output, simulated=args.dry_run)
    reader, browser, blog = QuoteReader(), None, None
    service, quote, fatal = None, None, None
    dump(output/'RUNNING.json', dict(pid=os.getpid(), at=now(), simulated=args.dry_run))
    try:
        identity = product_identity()
        dump(output/'disk-identity.json', identity)
        if not identity['qualified']:
            raise RuntimeError('DISK_VERSION_MISMATCH')
        if args.live and not START-timedelta(minutes=2) <= now() <= END:
            raise RuntimeError('OUTSIDE_FIXED_RUN_WINDOW')
        manifest = json.loads((ROOT/'scripts/rth_acceptance_manifest.json').read_text())
        for relative, expected in manifest['acceptance_files'].items():
            if hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError('ACCEPTANCE_CODE_DRIFT_'+relative)
        service = service_identity(start_if_absent=args.live)
        dump(output/'runtime-preflight.json', service)
        if args.preflight or args.live:
            quote = reader.read('preflight')
            dump(output/'opend-preflight.json', quote)
            if quote.get('error') or quote.get('right') not in ('LV1','LV2','LV3') or abs(quote.get('server_skew',999))>5:
                raise RuntimeError('OPEND_OR_CLOCK_PREFLIGHT_BLOCKED')
        if args.live or args.browser_seconds:
            blog = (output/'browser-process.log').open('ab')
            browser = subprocess.Popen([manifest['node'], str(ROOT/'scripts/rth_browser_acceptance.cjs'),
                str(output), str(END.timestamp() if args.live else time.time()+args.browser_seconds),
                manifest['playwright_module'], manifest['browser_executable']], cwd=ROOT, stdout=blog, stderr=blog, creationflags=FLAGS)
        if args.dry_run:
            # 使用完整真实时序计划加速走过所有采样点，但不请求报价，不伪造自然事件。
            state = readonly_state()
            for at in schedule():
                audit.sample(at, service, dict(opend='OFFLINE_SIMULATION', quotes={}), state)
            dump(output/'simulated-clock.json', dict(ticks=[x.isoformat() for x in schedule()],
                 start_hk=START.isoformat(), open_hk=OPEN.astimezone(HK).isoformat(), close_hk=CLOSE.astimezone(HK).isoformat(),
                 deadline_hk=END.isoformat(), not_real_market_evidence=True))
            if browser:
                browser.wait(timeout=args.browser_seconds+30)
                if browser.returncode != 0:
                    raise RuntimeError('BROWSER_PROCESS_FAILED_'+str(browser.returncode))
        else:
            first_done, first_attempts = False, 0
            for planned in schedule():
                if now() >= END:
                    break
                while now() < planned:
                    time.sleep(min(10, max(.01, (planned-now()).total_seconds())))
                at = now()
                if at >= END:
                    break
                # 休眠错过的采样不补造、不连续突发补发。
                if (at-planned).total_seconds()>45:
                    audit.error('MISSED_SCHEDULED_SAMPLE', at, service, quote)
                    continue
                try:
                    if not product_identity()['qualified']:
                        raise RuntimeError('DISK_VERSION_CHANGED_DURING_RUN')
                    service = service_identity(False)
                    quote = reader.read('quotes')
                    if quote.get('error'):
                        audit.error(quote['error'], at, service, quote)
                    state = readonly_state()
                    audit.sample(at, service, quote, state)
                    if not first_done and first_attempts < 3 and OPEN+timedelta(hours=1,minutes=2) <= at < CLOSE:
                        first_attempts += 1
                        first_hour(audit, reader.read('first_hour',timeout=45), now())
                        first_done = audit.items['首根1H']['status']=='PASS'
                    if browser and browser.poll() is not None and now() < CLOSE:
                        audit.verdict('双窗口与横竖屏', 'FAIL', '浏览器子进程提前退出；无无限重启')
                except Exception as exc:
                    if isinstance(exc, IdentityError):service=exc.details
                    audit.error(str(exc), at, service, quote)
                    if 'IDENTITY' in str(exc) or 'VERSION' in str(exc) or 'PORT_' in str(exc):
                        raise
    except BaseException as exc:
        if isinstance(exc, IdentityError):service=exc.details
        fatal = type(exc).__name__+': '+str(exc)
        audit.error(fatal, now(), service, quote)
    finally:
        reader.close()
        if browser and browser.poll() is None:
            # 浏览器读取STOP后自行关闭本程序创建的页面；不影响用户浏览器或8501。
            (output/'STOP').write_text('验收结束', encoding='utf-8')
            try:browser.wait(timeout=15)
            except subprocess.TimeoutExpired:
                browser.terminate();browser.wait(timeout=5)
        if blog:blog.close()
        audit.finish(blocked=fatal)
        lock.close()
    return 2 if fatal else 0


if __name__ == '__main__':
    mp.freeze_support()
    raise SystemExit(main())
