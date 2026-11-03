"""Independent daily archive. Never writes user plans or calls a data provider."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import pandas as pd
from .clock import CAL, ET, bounds
from .watchlist import normalize_symbol

BLOCK = '仅供应商日K；分钟时间契约、复权及聚合时段未确认；不授予1H ICT或实时资格。'


def validate_daily(payload, symbol, acquired_at):
    symbol = normalize_symbol(symbol)
    ticker = symbol[3:]
    request = payload.get('request', {})
    if payload.get('tool') != 'get_stock_bars' or request.get('timeframe') not in ('1Day', '1D'):
        raise ValueError('只接收get_stock_bars的1Day供应商JSON；不将分钟或其他周期当日K。')
    if request.get('symbols') != [ticker] or not request.get('feed'):
        raise ValueError('请求证券或数据feed与导入标的不一致/缺失。')
    acquired = pd.Timestamp(acquired_at)
    if acquired.tzinfo is None:
        raise ValueError('取得时间必须带时区。')
    if acquired > pd.Timestamp.now(tz='UTC')+pd.Timedelta(seconds=5):
        raise ValueError('取得时间在未来，不能作为历史数据完成证据。')
    start = pd.Timestamp(request['start']).tz_convert(ET).date()
    end = (pd.Timestamp(request['end']).tz_convert(ET)-pd.Timedelta(microseconds=1)).date()
    if end < start:
        raise ValueError('历史请求区间无效。')
    expected = {str(x.date()) for x in CAL.sessions_in_range(str(start), str(end))}
    records = []
    seen = set()
    for raw in payload.get('bars', {}).get(ticker, []):
        ts = pd.Timestamp(raw['timestamp'])
        if ts.tzinfo is None or raw.get('symbol') != ticker:
            raise ValueError('行情证券不符或时间缺少时区。')
        ts = ts.tz_convert(ET)
        day = str(ts.date())
        if ts.hour or ts.minute or ts.second or ts.microsecond or day not in expected:
            raise ValueError('日K标签不是纽约交易日零点，或超出请求交易日范围。')
        if day in seen:
            raise ValueError('供应商响应包含重复交易日。')
        if acquired.to_pydatetime() < bounds(ts.date())[1]+timedelta(minutes=2):
            raise ValueError('日K所属交易日尚未结束；拒绝形成中/未来数据。')
        seen.add(day)
        values = {k: float(raw[k]) for k in ('open','high','low','close','volume')}
        if not all(math.isfinite(v) for v in values.values()):
            raise ValueError('OHLCV含非有限数值。')
        o,h,l,c,v = (values[k] for k in ('open','high','low','close','volume'))
        if min(o,h,l,c)<=0 or v<0 or l>min(o,c) or h<max(o,c) or l>h:
            raise ValueError('OHLCV价格范围或成交量无效。')
        records.append(dict(date=day, timestamp=ts.isoformat(), **values))
    if not records:
        raise ValueError('供应商未返回日K；保留已有档案，不补值。')
    return sorted(records,key=lambda r:r['date']), str(start), str(end)


class DailyArchive:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as c, c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS daily_bars(symbol TEXT,day TEXT,payload TEXT,PRIMARY KEY(symbol,day));
            CREATE TABLE IF NOT EXISTS daily_coverage(symbol TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE IF NOT EXISTS daily_imports(id INTEGER PRIMARY KEY,at TEXT,symbol TEXT,sha256 TEXT,raw TEXT);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=15)

    def import_payload(self, payload, symbol, acquired_at=None):
        symbol=normalize_symbol(symbol)
        now=datetime.now(timezone.utc).isoformat()
        acquired_at=acquired_at or now
        records,start,end=validate_daily(payload,symbol,acquired_at)
        feed=payload['request']['feed']
        raw=json.dumps(payload,sort_keys=True,allow_nan=False)
        digest=hashlib.sha256(raw.encode()).hexdigest()
        with closing(self.connect()) as c, c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT payload FROM daily_coverage WHERE symbol=?',(symbol,)).fetchone()
            old=json.loads(old[0]) if old else None
            if old and old['feed']!=feed:
                raise ValueError('同一证券不混合不同feed；请使用独立档案。')
            existing={d:json.loads(p) for d,p in c.execute('SELECT day,payload FROM daily_bars WHERE symbol=?',(symbol,))}
            for row in records:
                if row['date'] in existing and existing[row['date']]!=row:
                    raise ValueError('同日OHLCV与已存档冲突，整次导入已拒绝；不静默覆盖历史。')
            added=sum(r['date'] not in existing for r in records)
            for row in records:
                c.execute('INSERT OR IGNORE INTO daily_bars VALUES(?,?,?)',(symbol,row['date'],json.dumps(row)))
                existing[row['date']]=row
            start=min(start,old['requested_start']) if old else start
            end=max(end,old['requested_end']) if old else end
            expected={str(x.date()) for x in CAL.sessions_in_range(start,end)}
            missing=sorted(expected-set(existing))
            coverage=dict(symbol=symbol,source='ALPACA / get_stock_bars',feed=feed,acquired_at=acquired_at,
                          imported_at=now,requested_start=start,requested_end=end,first=min(existing),last=max(existing),
                          bars=len(existing),expected=len(expected),missing=missing,status='DAILY_COMPLETE' if not missing else 'DAILY_PARTIAL',
                          chart_ready=True,daily_observation_eligible=not missing and len(existing)>=2,
                          adjustment='UNKNOWN_TOOL_NOT_EXPOSED',session_contract='VENDOR_DAY_UNVERIFIED',
                          ict_eligible=False,block_reason=BLOCK,last_raw_sha256=digest)
            c.execute('INSERT INTO daily_imports(at,symbol,sha256,raw) VALUES(?,?,?,?)',(now,symbol,digest,raw))
            c.execute('INSERT OR REPLACE INTO daily_coverage VALUES(?,?)',(symbol,json.dumps(coverage)))
        return dict(coverage,added=added)

    def read(self, symbol):
        with closing(self.connect()) as c:
            row=c.execute('SELECT payload FROM daily_coverage WHERE symbol=?',(symbol,)).fetchone()
            if not row:
                return None
            meta=json.loads(row[0])
            records=[json.loads(p) for p, in c.execute('SELECT payload FROM daily_bars WHERE symbol=? ORDER BY day',(symbol,))]
        frame=pd.DataFrame(records)
        frame['ts']=pd.to_datetime(frame.timestamp,utc=True).dt.tz_convert(ET)
        frame['session']='VENDOR_DAY'
        frame['eligible']=True  # Chart eligibility only; never RTH/ICT eligibility.
        frame['source']=meta['source']+'/'+meta['feed']
        return meta,frame

    def revision(self, symbol):
        with closing(self.connect()) as c:
            return c.execute('SELECT MAX(id) FROM daily_imports WHERE symbol=?',(symbol,)).fetchone()[0]

    def coverage(self):
        with closing(self.connect()) as c:
            return [json.loads(p) for p, in c.execute('SELECT payload FROM daily_coverage ORDER BY symbol')]
