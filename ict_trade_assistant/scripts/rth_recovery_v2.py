"""有界整场RTH观察控制器v2；冻结产品和旧入口保持不变。"""
from __future__ import annotations
import argparse
from datetime import datetime,timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
import unattended_rth_acceptance as frozen
from futu_minute_contract_audit import qualification
VERSION='RTH_RECOVERY_V2_20261103'
ET=ZoneInfo('America/New_York');HK=ZoneInfo('Asia/Hong_Kong')
SYMBOLS=frozen.SYMBOLS
FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)


class TemporaryServiceError(RuntimeError):pass


def write(path,value):frozen.dump(path,value)
def append(path,value):frozen.append(path,value)
def utcnow():return datetime.now(ET)


class Plan:
    def __init__(self,day):
        from desk.clock import bounds
        self.day=day
        b=bounds(datetime.fromisoformat(day).date())
        if not b:raise ValueError('NOT_TRADING_DAY')
        self.open,self.close=b;self.start=self.open-timedelta(minutes=15)
        self.deadline=self.close+timedelta(minutes=8)
        slots={self.start,self.open+timedelta(hours=1,minutes=2),self.close+timedelta(seconds=15),self.close+timedelta(minutes=2,seconds=5)}
        slots.update(self.open+timedelta(seconds=s) for s in range(0,301,15))
        slots.update(self.open+timedelta(minutes=m) for m in range(10,int((self.close-self.open).total_seconds()/60)+1,5))
        self.slots=sorted(t for t in slots if t<self.deadline)

    def rth(self,at):return self.open<=at<self.close
    def retry_seconds(self,at):return 60 if at<self.open+timedelta(minutes=5) else 300


class RealClock:
    def now(self):return utcnow()
    def until(self,target):
        while self.now()<target:time.sleep(min(5,max(.01,(target-self.now()).total_seconds())))


class SimClock:
    def __init__(self,at):self.at=at
    def now(self):return self.at
    def until(self,target):self.at=max(self.at,target)


def worker(directory):
    """只有OpenQuoteContext；每次请求均保存SDK阶段，身份返回只取行情权限。"""
    directory=Path(directory);ctx=None;subscribed=False
    def phase(request,name):
        value=dict(request_id=request['id'],phase=name,at=utcnow().isoformat(),pid=os.getpid())
        write(directory/'phase.json',value);append(directory/'phases.jsonl',value)
    try:
        for line in sys.stdin:
            request=json.loads(line)
            if request.get('command')=='stop':break
            try:
                phase(request,'SDK_IMPORT')
                import futu as ft
                from desk.provider import quote_quality
                if ctx is None:
                    phase(request,'SDK_INITIALIZING')
                    ctx=ft.OpenQuoteContext(host='127.0.0.1',port=11111)
                phase(request,'GLOBAL_STATE_REQUEST');sent=utcnow()
                ret,state=ctx.get_global_state();received=utcnow()
                response=dict(source='FUTU_OPEND',opend='UNKNOWN',request_sent_at=sent.isoformat(),received_at=received.isoformat(),
                    global_ret=ret,worker_pid=os.getpid(),quotes={},state={k:state.get(k) for k in ('qot_logined','timestamp','market_us','program_status_type')} if isinstance(state,dict) else {})
                if ret!=ft.RET_OK:response.update(error='GLOBAL_STATE_REJECTED',category='OPEND_RESPONSE_ERROR')
                elif state.get('qot_logined') not in (True,1,'1'):response.update(error='QUOTE_NOT_LOGGED_IN',category='QUOTE_LOGIN_UNAVAILABLE')
                else:
                    response['opend']='CONNECTED'
                    response['server_skew']=float(state['timestamp'])-received.timestamp()
                    phase(request,'PERMISSION_REQUEST');ret,user=ctx.get_user_info()
                    right=user.get('us_qot_right','UNKNOWN') if ret==ft.RET_OK else 'UNKNOWN'
                    response.update(right=right,permission_ret=ret)
                    if right not in ('LV1','LV2','LV3'):response.update(error='QUOTE_PERMISSION_UNVERIFIED',category='PERMISSION_INSUFFICIENT')
                    elif abs(response['server_skew'])>5:response.update(error='SERVER_CLOCK_SKEW',category='CLOCK_UNQUALIFIED')
                    elif request['command']=='quotes':
                        if not subscribed:
                            phase(request,'QUOTE_SUBSCRIBE')
                            ret,_=ctx.subscribe(list(SYMBOLS),[ft.SubType.QUOTE],subscribe_push=False,session=ft.Session.RTH)
                            response['subscribe_ret']=ret
                            if ret!=ft.RET_OK:response.update(error='QUOTE_SUBSCRIBE_REJECTED',category='SUBSCRIPTION_FAILED')
                            else:subscribed=True
                        if subscribed:
                            phase(request,'QUOTE_REQUEST');ret,frame=ctx.get_stock_quote(list(SYMBOLS))
                            response['quote_ret']=ret
                            if ret!=ft.RET_OK:response.update(error='QUOTE_REQUEST_REJECTED',category='QUOTE_RESPONSE_ERROR')
                            else:
                                for _,row in frame.iterrows():
                                    response['quotes'][row['code']]=quote_quality(row,right,utcnow(),response['server_skew'])
                                response['category']='DATA_STALE' if any(h['quality']=='STALE' for h in response['quotes'].values()) else 'RESPONSE_OK'
                    else:response['category']='PRECHECK_OK'
                response['response_completed_at']=utcnow().isoformat()
                phase(request,'RESPONSE_COMPLETE');write(directory/('response-'+request['id']+'.json'),response)
            except Exception as exc:
                write(directory/('response-'+request['id']+'.json'),dict(error='SDK_EXCEPTION_'+type(exc).__name__,category='SDK_OR_API_EXCEPTION',source='FUTU_OPEND',worker_pid=os.getpid(),received_at=utcnow().isoformat(),quotes={}))
    finally:
        if ctx is not None:ctx.close()


class Reader:
    def __init__(self,output,timeout=45):
        self.output=Path(output);self.timeout=timeout;self.process=None;self.logs=[];self.starts=0

    def read(self,command,at):
        began=time.monotonic()
        if self.process is None or self.process.poll() is not None:
            self.close();self.starts+=1
            self.directory=self.output/'workers'/str(self.starts);self.directory.mkdir(parents=True,exist_ok=False)
            self.logs=[(self.directory/'stdout.log').open('ab'),(self.directory/'stderr.log').open('ab')]
            self.process=subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--worker',str(self.directory)],
                cwd=ROOT,stdin=subprocess.PIPE,stdout=self.logs[0],stderr=self.logs[1],creationflags=FLAGS)
            write(self.directory/'owner.json',dict(pid=self.process.pid,created_at=utcnow(),controller_pid=os.getpid()))
        request=dict(id=uuid.uuid4().hex,command=command,issued_at=utcnow().isoformat())
        response_file=self.directory/('response-'+request['id']+'.json')
        try:
            self.process.stdin.write((json.dumps(request)+'\n').encode());self.process.stdin.flush()
            while time.monotonic()-began<self.timeout:
                if response_file.exists():
                    result=json.loads(response_file.read_text(encoding='utf-8'))
                    result.update(request_id=request['id'],elapsed_seconds=round(time.monotonic()-began,3))
                    if result.get('error'):self.close()
                    return result
                if self.process.poll() is not None:
                    exit_code=self.process.returncode
                    self.close()
                    return dict(error='OWN_WORKER_EXITED',category='OWN_WORKER_FAILURE',worker_exit=exit_code,
                        source='FUTU_OPEND',request_id=request['id'],received_at=utcnow().isoformat(),quotes={})
                time.sleep(.1)
            phase_file=self.directory/'phase.json'
            phase=json.loads(phase_file.read_text(encoding='utf-8')) if phase_file.exists() else {}
            if phase.get('request_id')!=request['id']:phase={}
            name=phase.get('phase','WORKER_STARTUP')
            category='SDK_INITIALIZATION_TIMEOUT' if name in ('SDK_IMPORT','SDK_INITIALIZING') else 'WORKER_STARTUP_TIMEOUT' if name=='WORKER_STARTUP' else 'OPEND_RESPONSE_TIMEOUT'
            result=dict(error='QUOTE_TIMEOUT',category=category,last_phase=phase,worker_pid=self.process.pid,
                source='FUTU_OPEND',request_id=request['id'],request_sent_at=request['issued_at'],received_at=utcnow().isoformat(),
                elapsed_seconds=round(time.monotonic()-began,3),quotes={})
            self.close();return result
        except (OSError,BrokenPipeError):
            self.close();return dict(error='OWN_WORKER_PIPE_FAILED',category='OWN_WORKER_FAILURE',source='FUTU_OPEND',quotes={},received_at=utcnow().isoformat())

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                try:self.process.stdin.write(b'{"command":"stop"}\n');self.process.stdin.flush()
                except (OSError,BrokenPipeError):pass
                try:self.process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    # 只使用本次Popen的进程句柄；没有按未知PID结束其他服务的路径。
                    self.process.terminate()
                    try:self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
            if self.process.stdin:
                try:self.process.stdin.close()
                except OSError:pass  # 已退出SDK的断管也必须清除句柄，不能阻塞下一次受控恢复。
            self.process=None
        for handle in self.logs:handle.close()
        self.logs=[]


def valid_quotes(response,at,plan):
    from desk.observations import live_health
    valid={}
    if response.get('error') or not plan.rth(at):return valid
    for symbol,h in response.get('quotes',{}).items():
        checked=live_health(h,at)
        if checked.get('quality')=='AVAILABLE':valid[symbol]=checked
    return valid


class SimulationReader:
    """仅--dry-run入口可构造；所有输出明确标记工程模拟。"""
    starts=0
    def __init__(self,plan,scenario='A'):self.plan=plan;self.scenario=scenario;self.calls=[]
    def read(self,command,at):
        self.calls.append(at)
        failed=self.scenario=='B' or (self.scenario=='A' and at<self.plan.open+timedelta(minutes=1))
        if failed:return dict(error='QUOTE_TIMEOUT',category='SIMULATED_SDK_INITIALIZATION_TIMEOUT',source='SIMULATED_ENGINEERING_ONLY',quotes={},received_at=at.isoformat())
        if command=='preflight':return dict(category='PRECHECK_OK',source='SIMULATED_ENGINEERING_ONLY',quotes={})
        quote_at=at-timedelta(seconds=120) if self.scenario=='C' else at
        quotes={s:dict(quality='STALE' if self.scenario=='C' else 'AVAILABLE',price=100.+(at-self.plan.open).total_seconds()/100000,
            quote_at=quote_at.isoformat(),received_at=at.isoformat(),age_seconds=120 if self.scenario=='C' else 0,
            right='LV3',source='SIMULATED_ENGINEERING_ONLY',server_clock_skew_seconds=0) for s in SYMBOLS}
        return dict(category='DATA_STALE' if self.scenario=='C' else 'RESPONSE_OK',source='SIMULATED_ENGINEERING_ONLY',quotes=quotes,
            raw_minutes=['09:31','16:00'] if self.scenario=='F' else [],received_at=at.isoformat())


class Controller:
    def __init__(self,plan,output,reader,clock,guard,view,simulated=False):
        self.plan=plan;self.output=Path(output);self.output.mkdir(parents=True,exist_ok=True)
        self.reader=reader;self.clock=clock;self.guard=guard;self.view=view;self.simulated=simulated
        self.records=[];self.next_check=plan.start;self.integrity_failed=False;self.was_blocked=False

    def run(self):
        for index,scheduled in enumerate(self.plan.slots):
            self.clock.until(scheduled);started=self.clock.now()
            if started>=self.plan.deadline:break
            record=dict(index=index,scheduled_at=scheduled.isoformat(),started_at=started.isoformat(),
                simulated=self.simulated,source='SIMULATED_ENGINEERING_ONLY' if self.simulated else 'FUTU_OPEND',status='MISSING',error_category=None,
                signal_status='UNKNOWN',ict_realtime=False,time_contract=qualification(),response=None,view=None)
            try:
                if (started-scheduled).total_seconds()>45:
                    record.update(error_category='MISSING_SCHEDULED_SLOT',reason='实际到达已超过45秒；不回填实时样本')
                else:
                    service_ready=False
                    if not self.integrity_failed and started>=self.next_check:
                        try:record['identity']=self.guard();service_ready=True
                        except TemporaryServiceError as exc:
                            record.update(error_category='SERVICE_UNAVAILABLE_NO_TAKEOVER',reason=str(exc))
                            self.next_check=started+timedelta(seconds=self.plan.retry_seconds(started));self.was_blocked=True
                        except Exception as exc:
                            self.integrity_failed=True
                            record['identity']=getattr(exc,'details',{})
                            record.update(error_category='SERVICE_IDENTITY_FAIL_CLOSED',reason=type(exc).__name__)
                    elif not self.integrity_failed:
                        record.update(error_category='RECOVERY_COOLDOWN',next_recovery_at=self.next_check.isoformat())
                    if self.integrity_failed:record.update(error_category='SERVICE_IDENTITY_FAIL_CLOSED',reason='完整性锁定；不连接行情、不接管端口')
                    elif service_ready:
                        response=self.reader.read('preflight' if scheduled==self.plan.start else 'quotes',started)
                        record['response']=response
                        if response.get('error'):
                            record.update(status='PRECHECK_BLOCKED' if scheduled==self.plan.start else 'MISSING',error_category=response.get('category','UNKNOWN_ERROR'))
                            self.next_check=started+timedelta(seconds=self.plan.retry_seconds(started));self.was_blocked=True
                        else:
                            valid=valid_quotes(response,self.clock.now(),self.plan)
                            record['qualified_quotes']=valid
                            record['status']='PRECHECK_OK' if scheduled==self.plan.start else 'LIVE' if set(valid)==set(SYMBOLS) else 'DATA_UNQUALIFIED'
                            record['error_category']=response.get('category') if record['status']=='DATA_UNQUALIFIED' else None
                            if self.was_blocked and set(valid)==set(SYMBOLS):
                                record['recovered_at']=self.clock.now().isoformat();self.was_blocked=False
                    if not self.integrity_failed:
                        try:record['view']=self.view()
                        except Exception as exc:record['view_error']='READONLY_VIEW_'+type(exc).__name__
            except Exception as exc:
                record.update(status='MISSING',error_category='CONTROLLER_OPERATION_ERROR',reason=type(exc).__name__)
                self.was_blocked=True;self.next_check=started+timedelta(seconds=self.plan.retry_seconds(started))
            record['completed_at']=self.clock.now().isoformat()
            identity=record.get('identity',{})
            listeners=identity.get('listeners',[])
            record['actual_runtime_pid']=listeners[0]['pid'] if listeners else identity.get('runtime',{}).get('pid')
            record['actual_runtime_fingerprint']=identity.get('runtime',{}).get('build_sha256') if identity.get('health_status')==200 else None
            record['runtime_metadata_fingerprint']=identity.get('runtime',{}).get('build_sha256')
            record['response_state']='NO_REQUEST_OR_NO_RESPONSE' if record['response'] is None else record['response'].get('category','UNKNOWN_RESPONSE')
            if record['status'] in ('MISSING','PRECHECK_BLOCKED'):
                record['gap_start']=scheduled.isoformat();record['gap_end']=record['completed_at']
            append(self.output/'attempts.jsonl',record);self.records.append(record)
            write(self.output/'checkpoint.json',dict(last_index=index,last_status=record['status'],at=record['completed_at'],planned=len(self.plan.slots)))
        return self.finish()

    def finish(self):
        from collections import Counter
        rth=[r for r in self.records if self.plan.rth(datetime.fromisoformat(r['started_at']))]
        qualified=[r for r in rth if r['status']=='LIVE']
        advancing={s:len({r.get('qualified_quotes',{}).get(s,{}).get('quote_at') for r in qualified}) for s in SYMBOLS}
        advancing_ok=all(n>=2 for n in advancing.values())
        missing=[r['index'] for r in rth if r['status'] in ('MISSING','PRECHECK_BLOCKED')]
        items={
            '完整计划观察':dict(status='PASS' if len(self.records)==len(self.plan.slots) else 'BLOCKED',planned=len(self.plan.slots),recorded=len(self.records)),
            '版本与端口':dict(status='FAIL' if self.integrity_failed else 'PASS'),
            '四ETF新报价推进':dict(status='PASS' if advancing_ok else 'BLOCKED',distinct_timestamps=advancing),
            '90秒门禁':dict(status='PASS' if qualified else 'NOT_OBSERVED',qualified_groups=len(qualified),note='沿用冻结live_health；未放宽阈值'),
            '分钟契约':dict(status='BLOCKED',reason='TIME_CONTRACT_UNRESOLVED'),
            'ICT实时事件':dict(status='BLOCKED',reason='PENDING_ICT_REALTIME；信号UNKNOWN，提醒关闭')}
        views=[r['view'] for r in self.records if r.get('view')]
        if views:
            from desk.observations import ranked
            rows=[ranked({s:o for s,o in v['observations'].items() if s in SYMBOLS})[:5] for v in views]
            items['Top5证券去重']=dict(status='FAIL' if any(len({r['symbol'] for r in rs})!=len(rs) or len(rs)>4 for rs in rows) else 'PASS' if any(rows) else 'NOT_OBSERVED')
            items['用户记录保持']=dict(status='PASS' if views[0]['protected']==views[-1]['protected'] else 'NOT_OBSERVED')
            events={e['id']:e for v in views for e in v['events']}
            write(self.output/'production-events.json',list(events.values()))
            items['市场事件去重']=dict(status='NOT_OBSERVED',reason='保存实际ID及dedupe，未由退出码或空记录证明自然转换')
        for name in ('候选距离随新行情变化','自然NEAR/INSIDE/OUTSIDE','自然断线安全降级与产品恢复','首根1H同期结构资格','生产备注提交保持'):
            items[name]=dict(status='NOT_OBSERVED',reason='逐样本保存只读生产观察；缺乏独立完整链时不授予通过')
        browser=[];path=self.output/'browser.jsonl'
        if path.exists():
            for line in path.read_text(encoding='utf-8').splitlines():
                try:browser.append(json.loads(line))
                except ValueError:pass
        live_browser=browser if self.simulated else [b for b in browser if self.plan.rth(datetime.fromisoformat(b['at']))]
        good=[b for b in live_browser if b.get('ok')];bad=[b for b in browser if not b.get('ok')]
        items['双窗口横竖屏']=dict(status='FAIL' if bad else 'PASS' if good else 'NOT_OBSERVED',checks=len(good),failures=len(bad))
        items['窗口选择与自动刷新']=dict(status='PASS' if {b.get('symbol') for b in good if b.get('refreshProven')}=={'SPY','QQQ'} else 'NOT_OBSERVED')
        items['ICT提醒锁定关闭']=dict(status='FAIL' if any(b.get('liveViolation') for b in browser) else 'PASS' if good else 'NOT_OBSERVED')
        status='BLOCKED' if not advancing_ok or self.integrity_failed else 'PARTIAL_EVIDENCE' if missing else 'COMPLETED_OBSERVATION'
        summary=dict(version=VERSION,date=self.plan.day,simulated=self.simulated,status=status,
            real_live_acceptance='PENDING_LIVE_ACCEPTANCE' if self.simulated else '逐项裁定；无整体通过',
            real_rth_samples=0 if self.simulated else len(qualified),simulated_qualified_groups=len(qualified) if self.simulated else 0,
            plan_start=self.plan.start.isoformat(),plan_open=self.plan.open.isoformat(),plan_close=self.plan.close.isoformat(),
            deadline=self.plan.deadline.isoformat(),completed_at=self.clock.now().isoformat(),attempt_count=len(self.records),
            planned_count=len(self.plan.slots),status_counts=dict(Counter(r['status'] for r in self.records)),
            rth_missing_indices=missing,recovery_times=[r['recovered_at'] for r in self.records if r.get('recovered_at')],
            worker_starts=getattr(self.reader,'starts',None),exit_code=2 if status=='BLOCKED' else 0,items=items,
            time_contract=qualification(),ict_realtime=False)
        write(self.output/'SUMMARY.json',summary)
        write(self.output/'gaps.json',[r for r in self.records if r['status'] in ('MISSING','PRECHECK_BLOCKED')])
        lines=['# RTH自动验收恢复v2报告','','【当前阶段】'+('模拟／Dry Run，真实RTH证据0' if self.simulated else '真实RTH有界观察结束'),
            '', '【执行状态】'+status+'；退出码不代表整体通过。','',f'【已完成】计划{len(self.plan.slots)}个观察点，实际保存{len(self.records)}条证据；此前缺口保持MISSING。',
            '', '【测试与证据】attempts.jsonl、gaps.json、worker阶段日志、生产只读快照和browser.jsonl均独立保存。',
            '', '| 项目 | 裁定 | 证据 |','|---|---|---|']
        lines.extend('| '+k+' | '+v['status']+' | '+json.dumps(v,ensure_ascii=False).replace('|','／')+' |' for k,v in items.items())
        lines+=['','【存在问题】TIME_CONTRACT_UNRESOLVED；新分钟不进入正式ICT识别。缺少自然事件或同期结构证据继续未观察，历史数据不回填成LIVE。',
            '', '【下一步】审阅逐项证据；实时ICT继续关闭。本程序不停止8501或OpenD，不访问交易账户，不自动创建下一场任务。']
        (self.output/'FINAL_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
        return summary


def guard():
    if not frozen.product_identity()['qualified']:raise RuntimeError('FROZEN_DISK_MISMATCH')
    try:return frozen.service_identity(start_if_absent=False)
    except frozen.IdentityError as exc:
        d=exc.details;r=d.get('runtime',{});ls=d.get('listeners',[])
        confirmed=(d.get('owned') and len(ls)==1 and r.get('pid')==ls[0]['pid'] and r.get('build_sha256')==frozen.BUILD
                   and r.get('port')==8501 and Path(r.get('root',''))==ROOT)
        if confirmed:raise TemporaryServiceError('OWN_SERVICE_HEARTBEAT_UNAVAILABLE') from exc
        raise
    except (OSError,subprocess.TimeoutExpired,ValueError) as exc:
        raise TemporaryServiceError('SERVICE_HEALTH_OR_METADATA_'+type(exc).__name__) from exc
    except RuntimeError as exc:
        if str(exc)=='PORT_ABSENT_OR_MULTIPLE_0':raise TemporaryServiceError('SERVICE_ABSENT_NO_AUTOSTART') from exc
        raise


def readonly_market_view():
    value=frozen.readonly_state()
    value['events']=[e for e in value['events'] if e['kind'] in ('MARKET_OBSERVATION','SYSTEM_HEALTH','DATA_HEALTH')]
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--worker',type=Path);p.add_argument('--date',default='2026-11-03')
    p.add_argument('--live',action='store_true');p.add_argument('--dry-run',action='store_true')
    p.add_argument('--output',type=Path);p.add_argument('--probe',action='store_true');p.add_argument('--scenario',choices=['A','B','C','F'],default='A')
    args=p.parse_args()
    if args.worker:worker(args.worker);return 0
    if args.live==args.dry_run:p.error('必须明确--live或--dry-run')
    plan=Plan(args.date)
    if args.live and (args.date!='2026-11-03' or args.output or args.probe):p.error('正式v2仅允许2026-11-03固定输出')
    output=args.output if args.dry_run else ROOT/'data/live_rth_acceptance/20261103'
    if output is None or (args.dry_run and output==ROOT/'data/live_rth_acceptance/20261103'):p.error('Dry Run必须独立目录')
    output.mkdir(parents=True,exist_ok=True)
    try:lock=frozen.acquire_lock(output/'run.lock')
    except RuntimeError:return 9
    if (output/'SUMMARY.json').exists():lock.close();return 10
    reader=Reader(output);browser=None;blog=None;controller=None
    try:
        manifest=json.loads((ROOT/'scripts/rth_recovery_v2_manifest.json').read_text(encoding='utf-8'))
        for name,digest in manifest['files'].items():
            if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('ACCEPTANCE_VERSION_DRIFT')
        if args.live and not plan.start-timedelta(minutes=2)<=utcnow()<=plan.deadline:raise RuntimeError('OUTSIDE_FIXED_WINDOW')
        if args.dry_run:
            guard()
            if args.probe:write(output/'actual-preflight.json',reader.read('preflight',utcnow()))
            clock=SimClock(plan.start)
            controller=Controller(plan,output,SimulationReader(plan,args.scenario),clock,lambda:dict(dry_run=True),readonly_market_view,True)
        else:
            clock=RealClock()
            # 浏览器可用性不由一次OpenD失败决定；只在正确8501上尝试一次。
            try:
                guard();blog=(output/'browser-process.log').open('ab')
                browser=subprocess.Popen([manifest['node'],str(ROOT/'scripts/rth_browser_recovery_v2.cjs'),str(output),
                    str(plan.deadline.timestamp()),manifest['playwright_module'],manifest['browser_executable'],
                    str(plan.open.timestamp())],cwd=ROOT,stdout=blog,stderr=blog,creationflags=FLAGS)
            except Exception as exc:append(output/'controller-errors.jsonl',dict(at=utcnow(),category='BROWSER_PRECHECK_BLOCKED',error=type(exc).__name__))
            controller=Controller(plan,output,reader,clock,guard,readonly_market_view)
        summary=controller.run()
        return summary['exit_code']
    except Exception as exc:
        write(output/'ENTRY_FAILURE.json',dict(at=utcnow(),status='BLOCKED',error=type(exc).__name__,code=str(exc)))
        if controller is None:controller=Controller(plan,output,reader,RealClock(),guard,lambda:{},args.dry_run)
        controller.integrity_failed=True;controller.finish()
        return 3
    finally:
        reader.close()
        if browser and browser.poll() is None:
            (output/'STOP').write_text('验收结束',encoding='utf-8')
            try:browser.wait(timeout=15)
            except subprocess.TimeoutExpired:browser.terminate();browser.wait(timeout=5)
        if blog:blog.close()
        lock.close()


if __name__=='__main__':raise SystemExit(main())
