"""V23C research messages, isolated from accounts, plans and ICT eligibility."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from .clock import ET, bounds

SOURCE_SHA = 'bb098c7fa0b5f88299df2f154a30edb2e80a6e0b25e0331cb61c7c9b4e8778e6'
STRATEGY = 'QQQ_V23C_P0_AB'
COMMON = {'schema','strategy','source_sha256','configuration_id','model_mode','symbol','timeframe','session','event'}
REQUEST = {'action','bar_open_ms','bar_close_ms','emitted_ms','confirmed','realtime','close',
           'target_exposure_pct','model_exposure_pct','model_position_qty','model_delta_qty',
           'market_level','boost_score','data_ready','external_finality'}
FILL = {'bar_open','filled_at','order_id','order_comment','model_order_action',
        'model_fill_qty','model_fill_price','model_position_after'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def number(value, low=-1e15, high=1e15):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('NUMBER_INVALID')
    return value


def instant(value, milliseconds=False):
    try:
        if milliseconds:
            number(value, 946684800000, 4102444800000)
            if int(value)!=value: raise ValueError()
            return datetime.fromtimestamp(value/1000, timezone.utc)
        result=datetime.fromisoformat(value.replace('Z','+00:00'))
        if result.tzinfo is None or result.utcoffset() is None: raise ValueError()
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError, AttributeError):
        raise ValueError('TIMESTAMP_INVALID') from None


def validate(payload, now):
    if not isinstance(payload,dict): raise ValueError('FIELDS_INVALID')
    is_fill=payload.get('schema')=='V23C_FILL_V1'
    if set(payload)-(COMMON | (FILL if is_fill else REQUEST) | {'message'}) or not (COMMON | (FILL if is_fill else REQUEST)) <= set(payload):
        raise ValueError('FIELDS_INVALID')
    if payload['strategy']!=STRATEGY or payload['source_sha256']!=SOURCE_SHA:
        raise ValueError('VERSION_INVALID')
    if payload['symbol']!='NASDAQ:QQQ': raise ValueError('SYMBOL_INVALID')
    if payload['timeframe'] not in ('D','1D'): raise ValueError('TIMEFRAME_INVALID')
    if payload['session']!='RTH': raise ValueError('SESSION_INVALID')
    if (isinstance(payload['model_mode'],bool) or payload['model_mode'] not in (0,1)):
        raise ValueError('MODE_INVALID')
    if not isinstance(payload['configuration_id'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}',payload['configuration_id']):
        raise ValueError('CONFIGURATION_INVALID')
    if 'message' in payload and (not isinstance(payload['message'],str) or len(payload['message'])>400):
        raise ValueError('FIELDS_INVALID')
    if is_fill:
        if payload['event']!='MODEL_FILL': raise ValueError('EVENT_INVALID')
        opened,at=instant(payload['bar_open']),instant(payload['filled_at'])
        for key in ('order_id','order_comment'):
            if not isinstance(payload[key],str) or not 1<=len(payload[key])<=128: raise ValueError('FIELDS_INVALID')
        if payload['model_order_action'] not in ('buy','sell'): raise ValueError('DIRECTION_INVALID')
        number(payload['model_fill_qty'],1e-12);number(payload['model_fill_price'],1e-12)
        number(payload['model_position_after'])
        window=bounds(opened.astimezone(ET).date())
        if not window or opened!=window[0] or not window[0] <= at <= window[1]:
            raise ValueError('FILL_TIME_INVALID')
        action={'Increase':'INCREASE','Reduce':'REDUCE','Reduce P0 Partial Close':'REDUCE','Target 0':'FLAT'}.get(payload['order_comment'],'OTHER')
        event_time,emitted=at,at
        key=['MODEL_FILL',payload['bar_open'],payload['filled_at'],payload['order_id'],
             payload['order_comment'],payload['model_fill_qty'],payload['model_fill_price']]
    else:
        if payload['schema']!='V23C_SIGNAL_V1': raise ValueError('VERSION_INVALID')
        if payload['event'] not in ('REQUEST','STATE'): raise ValueError('EVENT_INVALID')
        if payload['confirmed'] is not True: raise ValueError('UNCONFIRMED')
        if payload['realtime'] is not True: raise ValueError('HISTORICAL_REPLAY')
        if type(payload['data_ready']) is not bool or payload['external_finality']!='UNVERIFIED': raise ValueError('FIELDS_INVALID')
        opened,event_time,emitted=(instant(payload[k],True) for k in ('bar_open_ms','bar_close_ms','emitted_ms'))
        window=bounds(opened.astimezone(ET).date())
        if not window or (opened,event_time)!=window: raise ValueError('BOUNDARY_INVALID')
        if emitted<event_time: raise ValueError('UNCONFIRMED')
        number(payload['close'],1e-12);number(payload['target_exposure_pct'],0,135)
        number(payload['model_exposure_pct']);number(payload['model_position_qty'])
        delta=number(payload['model_delta_qty'])
        for key,high in (('market_level',5),('boost_score',9)):
            if int(number(payload[key],0,high))!=payload[key]: raise ValueError('NUMBER_INVALID')
        action=payload['action']
        if (action not in ('INCREASE','REDUCE','FLAT','HOLD') or
            (payload['event']=='STATE')!=(action=='HOLD') or
            (action=='INCREASE' and delta<=0) or (action in ('REDUCE','FLAT') and delta>=0) or
            (action=='FLAT' and payload['target_exposure_pct']!=0)):
            raise ValueError('DIRECTION_INVALID')
        key=['DECISION',payload['bar_close_ms']]
    if (emitted-now).total_seconds()>5 or (event_time-now).total_seconds()>5:
        raise ValueError('FUTURE_TIMESTAMP')
    delay=(now-event_time).total_seconds()
    quality='STALE' if delay>300 else 'DATA_GAP' if not is_fill and not payload['data_ready'] else 'FRESH'
    identity=[STRATEGY,payload['configuration_id'],payload['model_mode'],*key]
    logical={k:v for k,v in payload.items() if k not in ('emitted_ms','message')}
    return dict(event=payload['event'],action=action,event_at=event_time.isoformat(),quality=quality,
                event_key=hashlib.sha256(canonical(identity).encode()).hexdigest(),
                payload_sha=hashlib.sha256(canonical(logical).encode()).hexdigest())


class SignalStore:
    """Own database only. Existing files must already carry this store's marker."""
    def __init__(self,path,create=True):
        self.path=Path(path).resolve()
        if self.path.exists():
            try:
                with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
                    if db.execute('SELECT version FROM v23c_meta').fetchone()!=('V1',): raise ValueError()
            except (sqlite3.Error,ValueError):
                raise ValueError('FOREIGN_DATABASE') from None
        elif create:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with closing(sqlite3.connect(self.path)) as db:
                db.executescript('CREATE TABLE v23c_meta(version TEXT); INSERT INTO v23c_meta VALUES ("V1");'
                    'CREATE TABLE v23c_events(id INTEGER PRIMARY KEY,event_key TEXT UNIQUE,payload_sha TEXT,'
                    'event TEXT,action TEXT,event_at TEXT,received_at TEXT,quality TEXT,simulation INTEGER,payload TEXT);')
        else:
            raise FileNotFoundError(self.path)

    def ingest(self,payload,now=None,simulation=False):
        now=instant((now or datetime.now(timezone.utc)).isoformat())
        checked=validate(payload,now)
        with closing(sqlite3.connect(self.path,timeout=10)) as db:
            db.row_factory=sqlite3.Row
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT * FROM v23c_events WHERE event_key=?',(checked['event_key'],)).fetchone()
            if old:
                if old['payload_sha']!=checked['payload_sha']: raise ValueError('EVENT_CONFLICT')
                return dict(self._row(old),duplicate=True)
            cur=db.execute('INSERT INTO v23c_events(event_key,payload_sha,event,action,event_at,received_at,quality,simulation,payload) VALUES(?,?,?,?,?,?,?,?,?)',
                (checked['event_key'],checked['payload_sha'],checked['event'],checked['action'],checked['event_at'],now.isoformat(),
                 'SIMULATION' if simulation else checked['quality'],int(simulation),canonical(payload)))
            row=db.execute('SELECT * FROM v23c_events WHERE id=?',(cur.lastrowid,)).fetchone()
            db.commit()
            return dict(self._row(row),duplicate=False)

    @staticmethod
    def _row(row):
        result=dict(row);result['payload']=json.loads(result['payload'])
        result['simulation']=bool(result['simulation']);result['trading_eligible']=False
        return result

    def read(self,limit=100):
        with closing(sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True)) as db:
            db.row_factory=sqlite3.Row
            return [self._row(r) for r in db.execute('SELECT * FROM v23c_events ORDER BY event_at DESC,id DESC LIMIT ?',
                                                    (min(max(int(limit),1),1000),))]

    def latest_request(self):
        return next((r for r in self.read(1000) if r['event'] in ('REQUEST','STATE')),None)
