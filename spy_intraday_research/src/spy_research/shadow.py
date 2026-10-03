"""Resumable signal/quote observation; deliberately has NO broker/order imports."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import os
import time
import numpy as np
import pandas as pd
from .data import schedule, normalize, aggregate5_fast, quality, ohlcv_valid
from .features import build, apply_states
from .research import source_hash, corporate_dates
from .storage import normalized, read, write_json, write_csv, digest
from .setups import detect
from .review import table, daily, OBS_COLUMNS, EVENT_COLUMNS

def freeze_diagnostic(root,version='diagnostic_v2'):
    import re
    if not re.fullmatch(r'diagnostic_v[1-9][0-9]*',version): raise ValueError('INVALID_DIAGNOSTIC_VERSION')
    folder=root/'locks'/version; path=folder/'lock_manifest.json'
    if path.exists():
        lock=json.loads(path.read_text())
        if lock['source_sha256']!=source_hash() or lock['runtime_sha256']!=runtime_hash(): raise ValueError('DIAGNOSTIC_VERSION_SOURCE_CHANGED')
        return path
    model=root/'locks/baseline_v1/state_model.json'
    if not model.exists(): raise ValueError('TRAIN_STATE_MODEL_REQUIRED')
    lock=dict(version=version,mode='diagnostic-shadow',edge_status='UNVALIDATED',source_sha256=source_hash(),
        state_model_sha256=digest(model),state_model=json.loads(model.read_text()),horizon_minutes=30,
        additional_cost_bps=2.,max_quote_age_seconds=10,max_signal_delay_seconds=10,max_exit_delay_seconds=10,
        formal_data_gate=False,orders_enabled=False,primary_candidates='ALL_12_PREREGISTERED_NO_SELECTION',
        data_manifest_sha256=digest(root/'data/normalized/manifest.json'),
        created_at_utc=datetime.now(timezone.utc).isoformat(),runtime_sha256=runtime_hash(),account_processing_delay=True)
    write_json(path,lock); return path

def runtime_hash():
    import hashlib
    folder=Path(__file__).parent
    return hashlib.sha256(''.join(name+digest(folder/name) for name in ['shadow.py','review.py']).encode()).hexdigest()

@contextmanager
def exclusive(path):
    path.parent.mkdir(parents=True,exist_ok=True)
    try: fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError: raise ValueError('RUNNER_ALREADY_LOCKED_RECONCILE_BEFORE_RESTART')
    try:
        os.write(fd,str(os.getpid()).encode()); os.close(fd); yield
    finally: path.unlink(missing_ok=True)

def market_clock(now):
    now=pd.Timestamp(now)
    if now.tzinfo is None: raise ValueError('UTC_CLOCK_REQUIRED')
    day=now.tz_convert('America/New_York').strftime('%Y-%m-%d')
    calendar=schedule(day,day)
    if calendar.empty: return day,'CLOSED',None
    session=calendar.iloc[0]
    if now<session.open: return day,'PREOPEN',session
    if now>=session.close: return day,'CLOSED',session
    return day,'OPEN',session

class Session:
    def __init__(self,root,lock,date,warmup,actions):
        self.root,self.lock,self.date=root,lock,date
        self.warmup,self.actions=warmup,actions
        self.folder=root/'artifacts/paper'/lock['version']/date
        self.folder.mkdir(parents=True,exist_ok=True)
        self.events=table(self.folder/'events.csv',EVENT_COLUMNS)
        self.observations=table(self.folder/'observations.csv',OBS_COLUMNS)
        self.operational=table(self.folder/'operational.csv',['timestamp','status','reason'])
        self.last_bars=table(self.folder/'bars.csv',['ts_start_utc','ts_end_utc','session_date','code','open','high','low','close','volume'])
        if not self.last_bars.empty:
            for c in ['ts_start_utc','ts_end_utc']: self.last_bars[c]=pd.to_datetime(self.last_bars[c],utc=True)

    def persist(self):
        write_csv(self.folder/'events.csv',self.events); write_csv(self.folder/'observations.csv',self.observations)
        write_csv(self.folder/'operational.csv',self.operational); write_csv(self.folder/'bars.csv',self.last_bars)

    def log(self,now,status,reason):
        self.operational=pd.concat([self.operational,pd.DataFrame([dict(timestamp=pd.Timestamp(now).isoformat(),status=status,reason=reason)])],ignore_index=True)

    def step(self,bars,quote,now):
        processing_start=time.monotonic()
        now=pd.Timestamp(now)
        if market_clock(now)[1]!='OPEN': return 'CLOSED'
        bars=bars[(bars.session_date==self.date)&(bars.ts_end_utc<=now-pd.Timedelta(seconds=2))].copy()
        session=schedule(self.date,self.date).iloc[0]
        bars=bars[(bars.ts_start_utc>=session.open)&(bars.ts_end_utc<=session.close)]
        if bars.empty: self.log(now,'WAIT','NO_COMPLETED_BAR'); self.persist(); return 'WAIT'
        expected=pd.date_range(session.open,bars.ts_start_utc.max(),freq='min')
        if len(expected.difference(pd.DatetimeIndex(bars.ts_start_utc))):
            self.log(now,'PAUSED','MINUTE_GAP'); self.persist(); return 'PAUSED'
        if not ohlcv_valid(bars).all():
            self.log(now,'PAUSED','INVALID_LIVE_OHLCV'); self.persist(); return 'PAUSED'
        if (now-bars.ts_end_utc.max()).total_seconds()>90:
            self.log(now,'PAUSED','STALE_BARS'); self.persist(); return 'PAUSED'
        if not self.last_bars.empty:
            a=self.last_bars.set_index('ts_start_utc'); b=bars.set_index('ts_start_utc')
            common=a.index.intersection(b.index); columns=['open','high','low','close','volume']
            if not a.loc[common,columns].equals(b.loc[common,columns]):
                self.log(now,'PAUSED','COMPLETED_BAR_REVISION'); self.persist(); return 'PAUSED'
        self.last_bars=bars
        merged=pd.concat([self.warmup,bars],ignore_index=True).sort_values('ts_start_utc')
        features=apply_states(build(merged,aggregate5_fast(merged,partial=True),self.actions),self.lock['state_model'])
        _,detected=detect(features[features.session_date==self.date])
        detected=detected[detected.session_date==self.date]
        if self.lock.get('account_processing_delay',False):
            now=now+pd.Timedelta(seconds=time.monotonic()-processing_start)
        quote_time=pd.Timestamp(quote['timestamp']) if quote else None
        fresh=quote_time is not None and quote_time.tzinfo is not None and 0<=(now-quote_time).total_seconds()<=self.lock['max_quote_age_seconds'] and np.isfinite(quote['price']) and quote['price']>0
        if quote:
            with (self.folder/'quotes.jsonl').open('a',encoding='utf-8') as journal:
                journal.write(json.dumps(dict(received_at=now.isoformat(),quote_timestamp=str(quote_time),
                    price=float(quote['price']) if np.isfinite(quote['price']) else None,fresh=bool(fresh)),allow_nan=False)+'\n')
        if not fresh: self.log(now,'PAUSED','STALE_OR_INVALID_QUOTE')
        known=set(self.events.event_id)
        for event in detected.itertuples():
            if event.event_id in known: continue
            age=(now-event.signal_time).total_seconds()
            reason='AWAITING_POST_SIGNAL_QUOTE' if age<=self.lock['max_signal_delay_seconds'] else 'LATE_SIGNAL'
            item=dict(event_id=event.event_id,session_date=self.date,setup=event.setup,direction=event.direction,
                      signal_time=event.signal_time.isoformat(),available_at=now.isoformat(),status='DETECTED' if reason=='AWAITING_POST_SIGNAL_QUOTE' else 'SKIPPED',reason=reason)
            self.events=pd.concat([self.events,pd.DataFrame([item])],ignore_index=True)
            known.add(event.event_id)
        for index,event in self.events[self.events.status=='DETECTED'].iterrows():
            if (now-pd.Timestamp(event.signal_time)).total_seconds()>self.lock['max_signal_delay_seconds']:
                self.events.loc[index,['status','reason']]=['SKIPPED','POST_SIGNAL_QUOTE_NOT_AVAILABLE_IN_TIME']; continue
            if fresh and quote_time>=pd.Timestamp(event.available_at):
                self.events.loc[index,['status','reason']]=['OBSERVED','OK']
                observation=dict(event_id=event.event_id,session_date=self.date,setup=event.setup,direction=event.direction,
                    signal_time=event.signal_time,observed_at=now.isoformat(),entry_price=float(quote['price']),
                    exit_time=None,exit_price=None,gross_bps=None,net_bps=None,mfe_bps=0.,mae_bps=0.,status='OPEN',reason='',price_basis='RECEIVED_LAST_QUOTE_PROXY')
                self.observations=pd.concat([self.observations,pd.DataFrame([observation],columns=OBS_COLUMNS)],ignore_index=True)
        for i,row in self.observations[self.observations.status=='OPEN'].iterrows():
            due=pd.Timestamp(row.observed_at)+pd.Timedelta(minutes=self.lock['horizon_minutes'])
            if (now-due).total_seconds()>self.lock.get('max_exit_delay_seconds',10):
                self.observations.loc[i,['status','reason']]=['CENSORED','HORIZON_QUOTE_TOO_LATE']; continue
            if fresh:
                excursion=float(row.direction)*(float(quote['price'])/float(row.entry_price)-1)*10000
                self.observations.loc[i,'mfe_bps']=max(float(row.mfe_bps) if pd.notna(row.mfe_bps) else 0.,excursion)
                self.observations.loc[i,'mae_bps']=min(float(row.mae_bps) if pd.notna(row.mae_bps) else 0.,excursion)
            if now>=due and fresh and quote_time>=due:
                gross=float(row.direction)*(float(quote['price'])/float(row.entry_price)-1)*10000
                self.observations.loc[i,['exit_time','exit_price','gross_bps','net_bps','status']]=[now.isoformat(),float(quote['price']),gross,gross-self.lock['additional_cost_bps'],'COMPLETE']
        self.log(now,'OK' if fresh else 'PAUSED','QUOTE_PROXY_ONLY_NO_EXECUTION')
        self.persist(); return 'OK' if fresh else 'PAUSED'

    def finish(self,now,final_bars=None):
        if final_bars is not None:
            final_bars=final_bars[(final_bars.session_date==self.date)&(final_bars.ts_end_utc<=pd.Timestamp(now))].copy()
            _,check=quality(final_bars,self.date,self.date)
            if (check.status=='PASS').all(): self.last_bars=final_bars
            else: self.log(now,'PARTIAL','FINAL_MINUTE_SNAPSHOT_INCOMPLETE')
        open_rows=self.observations.status=='OPEN'
        self.observations.loc[open_rows,['status','reason']]=['CENSORED','NO_FRESH_QUOTE_AT_HORIZON_OR_CLOSE']
        self.events.loc[self.events.status=='DETECTED',['status','reason']]=['SKIPPED','NO_POST_SIGNAL_QUOTE_BEFORE_CLOSE']
        self.log(now,'COMPLETE','SESSION_FINISHED_NO_BROKER_POSITION')
        self.persist()
        quote_path=self.folder/'quotes.jsonl'
        if quote_path.exists(): write_csv(self.folder/'quotes.csv',pd.read_json(quote_path,lines=True))
        _,check=quality(self.last_bars,self.date,self.date)
        complete=bool((check.status=='PASS').all())
        write_json(self.folder/'session_summary.json',dict(session_date=self.date,canonical_bars_complete=complete,
                  orders_enabled=False,executable_fills=0,edge_status='UNVALIDATED'))
        return daily(self.root,self.lock['version'],self.date,session_status='COMPLETE' if complete else 'PARTIAL')

class LiveFeed:
    def __init__(self):
        from futu import OpenQuoteContext,SubType,RET_OK
        self.ctx=OpenQuoteContext(host=os.getenv('FUTU_HOST','127.0.0.1'),port=int(os.getenv('FUTU_PORT','11111')))
        ret,_=self.ctx.subscribe(['US.SPY'],[SubType.QUOTE,SubType.K_1M],subscribe_push=False)
        if ret!=RET_OK: self.close(); raise ValueError('LIVE_SUBSCRIPTION_REJECTED')

    def read(self):
        from futu import SubType,AuType,RET_OK
        ret,raw=self.ctx.get_cur_kline('US.SPY',1000,SubType.K_1M,AuType.NONE)
        if ret!=RET_OK: raise ValueError('LIVE_BAR_REQUEST_FAILED')
        ret,quote=self.ctx.get_stock_quote(['US.SPY'])
        if ret!=RET_OK or quote.empty: raise ValueError('LIVE_QUOTE_REQUEST_FAILED')
        row=quote.iloc[0]
        timestamp=pd.Timestamp(str(row.data_date)+' '+str(row.data_time)).tz_localize('America/New_York').tz_convert('UTC')
        return normalize(raw,'end'),dict(timestamp=timestamp,price=float(row.last_price))

    def close(self): self.ctx.close()

    def actions(self):
        ret,frame=self.ctx.get_rehab('US.SPY')
        if ret!=0 or 'ex_div_date' not in frame: raise ValueError('LIVE_CORPORATE_ACTIONS_UNAVAILABLE')
        return frame

def run(root,lock_path,once=False,poll_seconds=5,max_cycles=None):
    lock=json.loads(Path(lock_path).read_text())
    if lock['mode']!='diagnostic-shadow' or lock['orders_enabled'] or lock['source_sha256']!=source_hash() or lock['runtime_sha256']!=runtime_hash():
        raise ValueError('SHADOW_LOCK_INVALID_OR_CHANGED')
    minute,_,_=normalized(root)
    actions=corporate_dates(root)
    dayroot=root/'artifacts/paper'/lock['version']
    with exclusive(dayroot/'runner.lock'):
        active=None; feed=None; cycles=0
        try:
            while True:
                now=pd.Timestamp.now(tz='UTC'); date,status,_=market_clock(now)
                if active is not None and (status!='OPEN' or active.date!=date):
                    final_bars=None
                    if feed:
                        try: final_bars=feed.read()[0]
                        except Exception: active.log(now,'PARTIAL','FINAL_SNAPSHOT_FAILED')
                    active.finish(now,final_bars); active=None
                    if feed: feed.close(); feed=None
                if status=='OPEN':
                    if active is None:
                        prior=minute[minute.session_date<date].copy()
                        # Add completed future sessions without mutating registered historical data.
                        for path in sorted(dayroot.glob('*/bars.csv')):
                            if path.parent.name<date:
                                added=pd.read_csv(path,parse_dates=['ts_start_utc','ts_end_utc'])
                                _,check=quality(added,path.parent.name,path.parent.name)
                                if (check.status=='PASS').all(): prior=pd.concat([prior,added],ignore_index=True)
                        prior=prior.drop_duplicates(['code','ts_start_utc']).sort_values('ts_start_utc')
                        dates=sorted(prior.session_date.unique())[-60:]
                        prior=prior[prior.session_date.isin(dates)]
                        active=Session(root,lock,date,prior,actions)
                    try:
                        if feed is None:
                            feed=LiveFeed()
                            try:
                                actions_frame=feed.actions()
                                active.actions=set(pd.to_datetime(actions_frame.ex_div_date).dt.strftime('%Y-%m-%d'))
                                write_csv(active.folder/'corporate_actions.csv',actions_frame)
                            except Exception:
                                active.actions=actions|{date}  # Fail closed for Gap Fade only.
                                active.log(now,'PAUSED','GAP_FADE_DISABLED_CORPORATE_ACTIONS_UNQUALIFIED')
                        bars,quote=feed.read(); now=pd.Timestamp.now(tz='UTC'); status=active.step(bars,quote,now)
                    except Exception:
                        active.log(now,'PAUSED','LIVE_FEED_ERROR_RECONNECT_REQUIRED'); active.persist()
                        if feed: feed.close(); feed=None
                        status='PAUSED'
                write_json(dayroot/'runner_status.json',dict(timestamp=now.isoformat(),session_date=date,status=status,orders_enabled=False,
                    mode='diagnostic-shadow',next_action='wait for session' if status!='OPEN' else 'collect signals'))
                print(json.dumps(dict(session_date=date,status=status,orders_enabled=False)),flush=True)
                cycles+=1
                if once or (max_cycles is not None and cycles>=max_cycles):
                    if active: daily(root,lock['version'],date,session_status='PARTIAL')
                    break
                time.sleep(max(5,poll_seconds))
        finally:
            if feed: feed.close()
            if active: active.persist()
