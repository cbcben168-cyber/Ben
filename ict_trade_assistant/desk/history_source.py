"""Local saved history only. No sockets, quote subscriptions or fabricated bars."""
import copy
import json
from pathlib import Path
import pandas as pd
from .clock import ET


def missing_history(code, observed_at, reason=None):
    return dict(health=dict(quality='UNAVAILABLE', reason=reason or f'{code}：历史数据待加载；未提供已保存行情，不生成ICT信号。',
                           source='LOCAL_SAVED_HISTORY', received_at=observed_at.isoformat(), right='UNKNOWN'),
                minute=pd.DataFrame(), daily=pd.DataFrame(), errors=[], terminal_missing=True)


class HistorySource:
    def __init__(self, path, observed_at):
        self.path=Path(path)
        self.observed_at=observed_at
        self.raw=json.loads(self.path.read_text(encoding='utf-8'))
        self.cache={}

    def fetch(self, code):
        if code not in self.raw or not (self.raw[code].get('minute') or self.raw[code].get('daily')):
            return missing_history(code, self.observed_at)
        if code not in self.cache:
            value=copy.deepcopy(self.raw[code])
            for period in ('minute','daily'):
                frame=pd.DataFrame(value.get(period, []))
                if not frame.empty:
                    frame['ts']=pd.to_datetime(frame.ts,utc=True).dt.tz_convert(ET)
                value[period]=frame
            value['health'].update(quality='STALE',reason='既有真实历史快照；非实时行情',
                                   local_history_path=str(self.path), historical_observation_at=self.observed_at.isoformat())
            value['history_origin']=dict(path=str(self.path),observed_at=self.observed_at.isoformat(),
                                         source=value['health'].get('source','历史文件未提供原始来源'))
            self.cache[code]=value
        return copy.deepcopy(self.cache[code])
