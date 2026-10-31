"""有锁快照：不同窗口共用事实，不共用选股或输入状态。"""
import copy
import logging
import queue
import threading
import time
import pandas as pd
from .clock import now_et
LOG=logging.getLogger('ict.stability')

class MarketLoader:
    def __init__(self, fetch):
        self.fetch=fetch; self.lock=threading.Lock();self.pending={};self.results={};self.keys={}
        self.revisions={};self.failures={};self.retry_at={};self.updated={};self.jobs=queue.Queue()
        self.closed=threading.Event();self.reset_requested=False
        threading.Thread(target=self._work,daemon=True,name='ict-market-reader').start()

    def clear(self):
        with self.lock:
            self.keys.clear();self.failures.clear();self.retry_at.clear();self.reset_requested=True

    def get(self,code,cycle):
        with self.lock:
            auto=isinstance(cycle,tuple) and cycle[0]=='auto'
            # 手动窗口的本地计数不改变共享缓存键；显式 clear 才使快照失效。
            ttl=cycle[2] if auto and len(cycle)>2 else 60
            due=code not in self.keys or (auto and self.failures.get(code,0)<3 and time.monotonic()-self.updated.get(code,0)>=ttl)
            retry=0<self.failures.get(code,0)<3 and time.monotonic()>=self.retry_at.get(code,float('inf'))
            if code not in self.pending and (due or retry):
                done=threading.Event();self.pending[code]=(time.monotonic(),done)
                self.keys[code]=cycle[1] if auto else self.keys.get(code,-1)
                self.jobs.put((code,done))
            pending=self.pending.get(code)
        if pending:pending[1].wait(.02)
        with self.lock:
            if code in self.results:
                snapshot=copy.deepcopy(self.results[code])
                if self.failures.get(code,0)>=3:snapshot['health']['reason']+=' · 自动恢复已暂停，请手动刷新重新尝试。'
                return snapshot
            elapsed=time.monotonic()-self.pending[code][0] if code in self.pending else 0
        reason='行情正在后台读取；页面和人工计划可正常使用。' if elapsed<15 else 'OpenD 行情响应缓慢或连接超时；尚无可用行情，不允许新增入场审查。'
        return dict(health=dict(quality='UNAVAILABLE',loading=elapsed<15,reason=reason,source='FUTU_OPEND',right='UNKNOWN',received_at=now_et().isoformat()),minute=pd.DataFrame(),daily=pd.DataFrame(),errors=[])

    def diagnostics(self):
        with self.lock:return dict(pending=list(self.pending),revisions=dict(self.revisions),failures=dict(self.failures),queue=self.jobs.qsize())

    def _work(self):
        while not self.closed.is_set():
            try:code,done=self.jobs.get(timeout=1)
            except queue.Empty:continue
            try:
                with self.lock:
                    reset=self.reset_requested;self.reset_requested=False
                owner=getattr(self.fetch,'__self__',None)
                if reset and hasattr(owner,'reset_connection'):owner.reset_connection()
                result=self.fetch(code)
                if not isinstance(result,dict) or not isinstance(result.get('health'),dict):
                    raise ValueError('行情快照结构无效')
                for name in ['minute','daily']:
                    if not isinstance(result.get(name),pd.DataFrame):raise ValueError('行情周期结构无效')
            except Exception:
                LOG.exception('行情读取失败 symbol=%s',code)
                result=dict(health=dict(quality='UNAVAILABLE',reason='后台行情读取失败，请检查数据诊断。',source='FUTU_OPEND',right='UNKNOWN',received_at=now_et().isoformat()),minute=pd.DataFrame(),daily=pd.DataFrame(),errors=[])
            with self.lock:
                old=self.results.get(code,{})
                result=copy.deepcopy(result)
                retained=[]
                for period in ['minute','daily']:
                    if result.get(period,pd.DataFrame()).empty and not old.get(period,pd.DataFrame()).empty:
                        result[period]=old[period].copy(deep=True);retained.append(period)
                        result[period+'_snapshot_at']=old.get(period+'_snapshot_at',old.get('health',{}).get('received_at'))
                    elif not result.get(period,pd.DataFrame()).empty:
                        result[period+'_snapshot_at']=result.get(period+'_snapshot_at') or result['health'].get('received_at')
                if retained:
                    result['health']=dict(result['health'],quality='STALE',reason='读取失败，保留历史图表快照；禁止新增入场审查。')
                    result['retained_periods']=retained
                failed=result['health']['quality']=='UNAVAILABLE' or bool(retained)
                self.failures[code]=self.failures.get(code,0)+1 if failed else 0
                self.retry_at[code]=time.monotonic()+min(30,2**self.failures[code])
                self.revisions[code]=self.revisions.get(code,0)+1
                result['revision']=self.revisions[code]
                self.results[code]=result;self.updated[code]=time.monotonic();self.pending.pop(code,None)
            done.set();self.jobs.task_done()
