"""Quote-only live observations. No broker/account/order interfaces."""
import json
import math
import threading
import time
from pathlib import Path
import numpy as np
import pandas as pd
from .core import SPECS, RULE, calendar, contract_ok
from .cli import context, request, save, sha


def now():
    return pd.Timestamp.now(tz='UTC')


def fresh(stamp, received, seconds=10):
    return 0 <= (received-stamp).total_seconds() <= seconds


def prepare(frame, timezone, day, received):
    """Only a contiguous, completed cash-session prefix may produce signals."""
    frame=frame.copy()
    stamps=pd.to_datetime(frame.time_key).dt.tz_localize(timezone, ambiguous='raise', nonexistent='raise').dt.tz_convert('UTC')
    frame['ts']=stamps
    frame=frame[(frame.ts>=day.open)&(frame.ts+pd.Timedelta(minutes=1)<=received-pd.Timedelta(seconds=2))].sort_values('ts')
    if frame.empty:return frame
    expected=pd.date_range(day.open,frame.ts.iloc[-1],freq='min')
    if not frame.ts.reset_index(drop=True).equals(pd.Series(expected)):
        raise ValueError('MISSING_OR_DUPLICATE_MINUTE')
    latest=min(day.close-pd.Timedelta(minutes=1),(received-pd.Timedelta(seconds=2)).floor('min')-pd.Timedelta(minutes=1))
    if frame.ts.iloc[-1]<latest:raise ValueError('LATEST_COMPLETED_MINUTE_MISSING')
    prices=frame[['open','high','low','close']].astype(float)
    if not np.isfinite(prices).all().all() or (prices<=0).any().any():raise ValueError('INVALID_BAR_PRICES')
    if (prices.high<prices[['open','close','low']].max(axis=1)).any() or (prices.low>prices[['open','close']].min(axis=1)).any():
        raise ValueError('INVALID_BAR_RANGE')
    if not np.isclose(prices/.25,np.round(prices/.25),rtol=0,atol=1e-7).all():raise ValueError('INVALID_BAR_TICK')
    volumes=pd.to_numeric(frame.volume,errors='coerce')
    if not np.isfinite(volumes).all() or (volumes<0).any():raise ValueError('INVALID_BAR_VOLUME')
    return frame


def signal(frame, day):
    if len(frame)<15:return None
    five=frame.groupby(frame.ts.dt.floor('5min')).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),count=('close','count'))
    five=five[five['count']==5]
    opening=five.loc[day.open:day.open+pd.Timedelta(minutes=5)]
    if len(opening)!=2:return None
    high=float(opening.high.max());low=float(opening.low.min());width=high-low
    if width<=0:return None
    ends=five.index+pd.Timedelta(minutes=5)
    cutoff=day.open+pd.Timedelta(minutes=60)
    eligible=five[(five.index>=day.open+pd.Timedelta(minutes=10))&(ends<cutoff)]
    hits=eligible[(eligible.close>high)|(eligible.close<low)]
    if hits.empty:return None
    row=hits.iloc[0];direction=1 if row.close>high else -1
    raw=high-.25*width if direction==1 else low+.25*width
    stop=(math.floor(raw/.25) if direction==1 else math.ceil(raw/.25))*.25
    return dict(at=(hits.index[0]+pd.Timedelta(minutes=5)).isoformat(),direction=direction,or_high=high,or_low=low,stop=stop)


class Forward:
    def __init__(self,root):
        self.root=Path(root);self.lock=threading.RLock();self.stop_event=threading.Event();self.thread=None
        self.state=dict(status='STOPPED',orders_enabled=False,mode='DIAGNOSTIC_LIVE_QUOTE_PROXY',formal_data_gate=False)
        self.position=None;self.session=None;self.seen=False;self.eligible=False;self.previous_quote=None
        self.events=[];self.config=None;self.last_report=None
        checkpoint=self.root/'state/forward_checkpoint.json'
        if checkpoint.exists():
            old=json.loads(checkpoint.read_text())
            self.state.update(status='RECOVERY_REQUIRED' if old.get('position') else 'STOPPED',previous_run=old.get('state'),unresolved_position=old.get('position'))
            self.session=old.get('session');self.seen=old.get('seen',False)

    def snapshot(self):
        with self.lock:return dict(self.state,position=self.position,config=self.config,last_events=self.events[-15:])

    def event(self,kind,**values):
        with self.lock:
            item=dict(received_at_utc=now().isoformat(),kind=kind,**values)
            self.events.append(item)
            self.events=self.events[-200:]
            folder=self.root/'artifacts/forward'/now().tz_convert('America/New_York').strftime('%Y-%m-%d')
            folder.mkdir(parents=True,exist_ok=True)
            with (folder/'events.jsonl').open('a',encoding='utf-8') as file:file.write(json.dumps(item,allow_nan=False)+'\n')
            self.checkpoint()

    def checkpoint(self):
        save(self.root/'state/forward_checkpoint.json',dict(state=self.state,position=self.position,config=self.config,session=self.session,seen=self.seen))

    def start(self,config):
        with self.lock:
            if self.thread and self.thread.is_alive():raise ValueError('ALREADY_RUNNING')
            if self.state.get('status')=='RECOVERY_REQUIRED':raise ValueError('UNRESOLVED_PREVIOUS_OBSERVATION')
            product=config.get('product');contract=config.get('contract','')
            if product not in SPECS or not contract_ok(contract,product):raise ValueError('EXPLICIT_CONTRACT_REQUIRED')
            if config.get('timezone') not in ['America/New_York','America/Chicago']:raise ValueError('TIMEZONE_REQUIRED')
            fee=float(config['fee']);raw_slip=float(config['slip'])
            if not math.isfinite(fee) or not math.isfinite(raw_slip) or not raw_slip.is_integer() or fee<0 or raw_slip<0 or raw_slip>20:raise ValueError('COSTS_INVALID')
            slip=int(raw_slip)
            expiry=pd.Timestamp(config['expires_on']).strftime('%Y-%m-%d')
            if expiry<=now().tz_convert('America/New_York').strftime('%Y-%m-%d'):raise ValueError('EXPIRY_INVALID')
            if self.position:raise ValueError('POSITION_ALREADY_OBSERVED')
            self.config=dict(product=product,contract=contract,timezone=config['timezone'],fee=fee,slip=slip,expires_on=expiry,
                basis='USER_DECLARED_UNQUALIFIED',entry_model='FRESH_LAST_QUOTE_WITHIN_10_SECONDS_AFTER_SIGNAL_NOT_EXACT_OPEN',rule=RULE,
                source_sha256=sha(Path(__file__)))
            self.stop_event.clear();self.previous_quote=None;self.eligible=False
            self.state.update(status='CONNECTING',error=None,started_at_utc=now().isoformat())
            self.event('REGISTER',config=self.config)
            self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()

    def pause(self):
        with self.lock:
            # Keep observing an open proxy position; pause blocks new entries only.
            self.state['paused']=True;self.event('PAUSE_NEW_ENTRIES')

    def resume(self):
        with self.lock:self.state['paused']=False;self.event('RESUME_NEW_ENTRIES')

    def tick(self,frame,quote,received,day):
        date=day.name.strftime('%Y-%m-%d')
        if self.session!=date:
            if self.position:raise ValueError('UNRESOLVED_PRIOR_SESSION')
            self.session=date;self.seen=False;self.previous_quote=None
            self.eligible=received<=day.open+pd.Timedelta(minutes=10)
            self.event('SESSION',session_date=date,entry_eligible=self.eligible)
        stamp=pd.Timestamp(str(quote['data_date'])+' '+str(quote['data_time'])).tz_localize(self.config['timezone']).tz_convert('UTC')
        price=float(quote['last_price'])
        if not math.isfinite(price) or price<=0 or not np.isclose(price/.25,round(price/.25),rtol=0,atol=1e-7):raise ValueError('INVALID_QUOTE')
        if not fresh(stamp,received):raise ValueError('STALE_QUOTE')
        if self.previous_quote is not None and stamp<=self.previous_quote:return
        if self.previous_quote is not None and (stamp-self.previous_quote).total_seconds()>10:
            self.eligible=False;self.state['data_gap']=True;self.event('QUOTE_GAP')
            if self.position:
                self.event('POSITION_INVALIDATED',position=self.position,reason='UNOBSERVED_PRICE_PATH')
                self.position=None;self.seen=True
        self.previous_quote=stamp
        self.state.update(last_quote_utc=stamp.isoformat(),received_at_utc=received.isoformat(),last_price=price,status='PAUSED' if self.state.get('paused') else 'OBSERVING')
        cfg=self.config;direction=self.position['direction'] if self.position else 0
        bars=prepare(frame,cfg['timezone'],day,received)
        self.state['completed_minutes']=len(bars)
        self.event('QUOTE',quote_time_utc=stamp.isoformat(),last_price=price)
        save(self.root/'artifacts/forward'/date/'completed_bars.csv',bars.to_csv(index=False))
        if self.position:
            pos=self.position
            stop=direction*(price-pos['stop'])<=0
            target=direction*(price-pos['target'])>=.25
            close=received>=day.close
            if stop or target or close:
                exit_price=pos['target'] if target and not stop else price-direction*cfg['slip']*.25
                net=direction*(exit_price-pos['entry_price'])*SPECS[cfg['product']]['point_value']-cfg['fee']
                self.event('EXIT_PROXY',reason='STOP' if stop else 'TARGET' if target else 'RTH_CLOSE',exit_price=exit_price,net_usd=net,position=pos)
                self.position=None
        elif not self.seen and received<day.close:
            found=signal(bars,day)
            if found:
                self.seen=True;self.event('SIGNAL',**found)
                boundary=pd.Timestamp(found['at'])
                if not self.eligible or self.state.get('paused') or not fresh(boundary,received) or stamp<boundary:
                    self.event('ENTRY_SKIPPED',reason='LATE_START_PAUSED_OR_LATE_SIGNAL')
                elif found['direction']*(price-found['stop'])<=0:self.event('ENTRY_SKIPPED',reason='ENTRY_BEYOND_STOP')
                else:
                    entry=price+found['direction']*cfg['slip']*.25
                    risk=found['direction']*(entry-found['stop'])
                    self.position=dict(**found,entry_price=entry,target=entry+found['direction']*3*risk,entry_received_at_utc=received.isoformat())
                    self.event('ENTRY_PROXY',position=self.position)
        if received>=day.close and self.last_report!=date:
            self.report(date);self.last_report=date
        self.checkpoint()

    def report(self,date):
        folder=self.root/'artifacts/forward'/date
        folder.mkdir(parents=True,exist_ok=True)
        events_path=folder/'events.jsonl'
        session_events=[json.loads(line) for line in events_path.read_text(encoding='utf-8').splitlines()] if events_path.exists() else []
        exits=[e for e in session_events if e['kind']=='EXIT_PROXY']
        signals=sum(e['kind']=='SIGNAL' for e in session_events)
        skips=sum(e['kind']=='ENTRY_SKIPPED' for e in session_events)
        invalid=sum(e['kind']=='POSITION_INVALIDATED' for e in session_events)
        failures=sum(e['kind'] in ['DATA_BLOCKED','QUOTE_GAP','ERROR'] for e in session_events)
        recommendation=('优先核验连接、数据完整性和时间语义；缺失路径不能用于交易优化。' if invalid or failures else
                        '优先检查启动时间和信号可用延迟，再另建入场差异研究。' if skips else
                        '保持冻结规则收集更多完整日样本；当前不足以改动止盈止损。')
        pd.DataFrame(session_events).to_csv(folder/'observations.csv',index=False)
        choices=[dict(option='KEEP_FROZEN',description='继续原规则收集样本',status='AWAITING_USER_CHOICE'),
                 dict(option='QUALIFY_DATA_AND_COSTS',description='核验时间语义、行情完整性与真实费用',status='AWAITING_USER_CHOICE'),
                 dict(option='REGISTER_ENTRY_STUDY',description='另建下一根开盘与延迟报价差异研究，不改当前规则',status='AWAITING_USER_CHOICE')]
        if not (folder/'optimization_choices.csv').exists():pd.DataFrame(choices).to_csv(folder/'optimization_choices.csv',index=False)
        save(folder/'report.md',f'# {date} ES/MES 实时诊断总结\n\n信号 {signals} 个；跳过入场 {skips} 个；无效持仓 {invalid} 个；数据异常事件 {failures} 个。\n\n有效完成模拟报价成交 {len(exits)} 笔；净美元合计 {sum(e["net_usd"] for e in exits):.2f}。这是按声明费用和滑点计算的报价代理结果，非券商成交、非精确开盘成交；无有效交易时合计零不代表策略表现。\n\n当日建议：{recommendation}\n\n缺口或迟到会取消交易资格。单日结果不能证明 edge；当前决定 WEAK / DATA_UNQUALIFIED。\n\n优化候选：保持冻结、核验数据及费用、注册独立入场延迟研究。等待用户选择，不自动改规则。\n')
        self.event('DAILY_REPORT',session_date=date)

    def loop(self):
        ctx=None
        try:
            from futu import SubType,KLType,AuType
            ctx=context();cfg=self.config
            request(ctx.subscribe,[cfg['contract']],[SubType.QUOTE,SubType.K_1M],subscribe_push=False)
            failures=0
            while not self.stop_event.is_set():
                received=now();date=received.tz_convert('America/New_York').strftime('%Y-%m-%d')
                cal=calendar(date,date)
                with self.lock:
                    if date>=cfg['expires_on']:raise ValueError('CONTRACT_EXPIRED_SELECT_NEW_CONTRACT')
                    if cal.empty or received<cal.iloc[0].open or received>cal.iloc[0].close+pd.Timedelta(minutes=1):
                        if not cal.empty and received>cal.iloc[0].close and self.session==date and self.last_report!=date:
                            if self.position:
                                self.event('POSITION_INVALIDATED',position=self.position,reason='MISSING_FRESH_CLOSE_QUOTE');self.position=None
                            self.report(date);self.last_report=date
                        self.state.update(status='PAUSED' if self.state.get('paused') else 'WAITING_CASH_SESSION',heartbeat_utc=received.isoformat());self.checkpoint()
                        day=None
                    else:day=cal.iloc[0]
                if day is not None:
                    try:
                        bars=request(ctx.get_cur_kline,cfg['contract'],1000,ktype=KLType.K_1M,autype=AuType.NONE)[0]
                        quotes=request(ctx.get_stock_quote,[cfg['contract']])[0]
                        with self.lock:self.tick(bars,quotes.iloc[0],now(),day)
                        failures=0
                    except Exception as exc:
                        failures+=1
                        with self.lock:
                            self.eligible=False
                            self.state.update(status='DATA_BLOCKED',error=safe_error(exc));self.event('DATA_BLOCKED',error=safe_error(exc))
                            if self.position:
                                self.event('POSITION_INVALIDATED',position=self.position,reason='DATA_FAILURE');self.position=None;self.seen=True
                        if failures>=3:raise ValueError('DATA_FAILURE_RETRY_LIMIT')
                self.stop_event.wait(3 if day is not None else 30)
        except Exception as exc:
            with self.lock:self.state.update(status='WAITING_PERMISSION' if safe_error(exc)=='FUTURES_PERMISSION_DENIED' else 'ERROR',error=safe_error(exc));self.event('ERROR',error=safe_error(exc))
        finally:
            if ctx is not None:ctx.close()


def safe_error(exc):
    text=str(exc)
    return text if text.isupper() and len(text)<100 else 'CHECK_DATA_CONNECTION_AND_INPUTS'
