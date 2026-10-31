import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULTS = dict(watchlist=['US.SPY', 'US.QQQ', 'US.IWM', 'US.SOXX'],
                distance_bps=10.0, refresh_seconds=60, layers=True, zones={}, candidate_atr=.25)


def stamp():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connect() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS plan_versions(plan_id TEXT,version INTEGER,at TEXT,status TEXT,symbol TEXT,payload TEXT,PRIMARY KEY(plan_id,version));
            CREATE TABLE IF NOT EXISTS acknowledgements(event_id INTEGER PRIMARY KEY,at TEXT);
            CREATE TABLE IF NOT EXISTS notes(symbol TEXT PRIMARY KEY,body TEXT,at TEXT);
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,at TEXT,key TEXT,old TEXT,new TEXT);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,at TEXT,kind TEXT,symbol TEXT,reason TEXT,payload TEXT,dedupe TEXT UNIQUE);
            CREATE TABLE IF NOT EXISTS bars(symbol TEXT,ts TEXT,period TEXT,session TEXT,payload TEXT,
                PRIMARY KEY(symbol,ts,period,session));
            CREATE TABLE IF NOT EXISTS levels(symbol TEXT,day TEXT,name TEXT,payload TEXT,
                PRIMARY KEY(symbol,day,name));
            CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY,at TEXT,symbol TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS observation_states(channel TEXT,symbol TEXT,key TEXT,scope TEXT,state TEXT,data_at TEXT,
                PRIMARY KEY(channel,symbol,key,scope));
            CREATE TABLE IF NOT EXISTS observation_snapshots(symbol TEXT PRIMARY KEY,signature TEXT,payload TEXT);
            ''')

    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.path, timeout=15)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def settings(self):
        with self.connect() as c:
            saved = dict(c.execute('SELECT key,value FROM settings'))
        return {k: json.loads(saved[k]) if k in saved else v for k, v in DEFAULTS.items()}

    def save(self, key, value):
        settings = self.settings()
        old = settings.get(key)
        if old == value:
            return
        with self.connect() as c:
            c.execute('INSERT INTO audit(at,key,old,new) VALUES(?,?,?,?)',
                      (stamp(), key, json.dumps(old), json.dumps(value)))
            c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (key, json.dumps(value)))
            if key in {'candidate_atr','zones'}:
                from .observations import parameter_version
                c.execute('INSERT INTO audit(at,key,old,new) VALUES(?,?,?,?)',
                          (stamp(),'observation_parameter_version',json.dumps(parameter_version(settings)),
                           json.dumps(parameter_version(dict(settings,**{key:value})))))

    def event(self, kind, symbol, reason, payload=None, dedupe=None, plan_guard=None):
        with self.connect() as c:
            if plan_guard:
                c.execute('BEGIN IMMEDIATE')
                latest=c.execute('SELECT version,status FROM plan_versions WHERE plan_id=? ORDER BY version DESC LIMIT 1',(plan_guard[0],)).fetchone()
                if latest != (plan_guard[1],'ACTIVE'):
                    return
            c.execute('INSERT OR IGNORE INTO events(at,kind,symbol,reason,payload,dedupe) VALUES(?,?,?,?,?,?)',
                      (stamp(), kind, symbol, reason, json.dumps(payload or {}, default=str), dedupe))

    def record(self, symbol, observation):
        with self.connect() as c:
            c.execute('INSERT INTO observations(at,symbol,payload) VALUES(?,?,?)',
                      (stamp(), symbol, json.dumps(observation, default=str)))

    def observation(self, value):
        import hashlib
        # 评估时钟每次变化；事实、参数、数据时间相同不追加重复记录。
        evidence={k:v for k,v in value.items() if k not in {'evaluated_at','health'}}
        payload=json.dumps(evidence,sort_keys=True,default=str)
        signature=hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT signature FROM observation_snapshots WHERE symbol=?',(value['symbol'],)).fetchone()
            if old and old[0]==signature: return
            c.execute('INSERT OR REPLACE INTO observation_snapshots VALUES(?,?,?)',(value['symbol'],signature,payload))
            c.execute('INSERT INTO observations(at,symbol,payload) VALUES(?,?,?)',(stamp(),value['symbol'],payload))

    def transition(self, channel, symbol, key, state, data_at, reason, payload, scope):
        """事务内比较状态；同一数据刷新、旧快照和并发窗口均不重复写事件。"""
        import hashlib
        import pandas as pd
        ts = pd.Timestamp(data_at)
        if ts.tzinfo is None:
            raise ValueError('状态时间必须带时区')
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            identity = (channel, symbol, key, scope)
            old = c.execute('SELECT state,data_at FROM observation_states WHERE channel=? AND symbol=? AND key=? AND scope=?', identity).fetchone()
            if old and ts <= pd.Timestamp(old[1]):
                return
            c.execute('INSERT OR REPLACE INTO observation_states VALUES(?,?,?,?,?,?)', (*identity, state, str(ts)))
            if (old and old[0] == state) or (not old and state == 'OUTSIDE'):
                return
            kind = 'MARKET_OBSERVATION' if channel == 'MARKET' else 'SYSTEM_HEALTH'
            if channel=='SYSTEM' and old and old[0]!='AVAILABLE' and state=='AVAILABLE':
                reason='数据恢复 · '+reason
            value = dict(payload, previous_state=old[0] if old else None, state=state, channel=channel)
            digest = hashlib.sha256(json.dumps([*identity, state, str(ts)], ensure_ascii=False).encode()).hexdigest()
            c.execute('INSERT OR IGNORE INTO events(at,kind,symbol,reason,payload,dedupe) VALUES(?,?,?,?,?,?)',
                      (stamp(), kind, symbol, reason, json.dumps(value, default=str), digest))

    def bars(self, symbol, frame, period):
        with self.connect() as c:
            for row in frame.to_dict('records'):
                c.execute('INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?)',
                          (symbol, str(row['ts']), period, row['session'], json.dumps(row, default=str)))

    def levels(self, symbol, day, values):
        with self.connect() as c:
            for name, value in values.items():
                c.execute('INSERT OR REPLACE INTO levels VALUES(?,?,?,?)',
                          (symbol, str(day), name, json.dumps(value, default=str)))

    def table(self, name):
        if name not in {'events', 'audit', 'observations','market_events','system_events'}:
            raise ValueError('table not allowed')
        import pandas as pd
        where=''
        if name in {'market_events','system_events'}:
            where=" WHERE kind "+('IN' if name=='system_events' else 'NOT IN')+" ('DATA_HEALTH','SYSTEM_HEALTH')"
            name='events'
        with self.connect() as c:
            return pd.read_sql_query(f'SELECT * FROM {name}{where} ORDER BY id DESC LIMIT 300', c)

    def note(self, symbol, body=None):
        with self.connect() as c:
            if body is not None:
                c.execute('INSERT OR REPLACE INTO notes VALUES(?,?,?)', (symbol, body, stamp()))
            row = c.execute('SELECT body FROM notes WHERE symbol=?', (symbol,)).fetchone()
            return row[0] if row else ''

    def acknowledge(self, event_id):
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO acknowledgements VALUES(?,?)', (int(event_id), stamp()))

    def acknowledged(self):
        with self.connect() as c:
            return {r[0] for r in c.execute('SELECT event_id FROM acknowledgements')}

    def plans(self, symbol=None):
        with self.connect() as c:
            rows = c.execute("SELECT p.plan_id,p.version,p.at,p.status,p.symbol,p.payload FROM plan_versions p JOIN (SELECT plan_id,MAX(version) v FROM plan_versions GROUP BY plan_id) latest ON p.plan_id=latest.plan_id AND p.version=latest.v ORDER BY p.at DESC").fetchall()
        return [dict(json.loads(r[5]),plan_id=r[0],version=r[1],updated_at=r[2],status=r[3],symbol=r[4]) for r in rows if symbol is None or r[4]==symbol]

    def plan_history(self, plan_id):
        with self.connect() as c:
            return [dict(json.loads(r[2]),version=r[0],status=r[1]) for r in c.execute('SELECT version,status,payload FROM plan_versions WHERE plan_id=? ORDER BY version', (plan_id,))]

    def save_plan(self, payload, plan_id=None, expected_version=0, cancel=False):
        import uuid
        from .plans import validate_plan
        validate_plan(payload)
        plan_id = plan_id or str(uuid.uuid4())
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            last = c.execute('SELECT version,status FROM plan_versions WHERE plan_id=? ORDER BY version DESC LIMIT 1',(plan_id,)).fetchone()
            if (last[0] if last else 0) != expected_version:
                raise ValueError('计划已被其他窗口更新，请重新载入后修改。')
            if last and last[1]=='CANCELLED':
                raise ValueError('已取消的计划不可恢复，请建立新计划。')
            payload = {k:v for k,v in payload.items() if k not in {'plan_id','version','status','updated_at'}}
            if last:
                original = c.execute('SELECT payload FROM plan_versions WHERE plan_id=? AND version=1',(plan_id,)).fetchone()
                payload['created_at'] = json.loads(original[0])['created_at']
            else: payload['created_at'] = stamp()
            version = expected_version+1
            status = 'CANCELLED' if cancel else 'ACTIVE'
            c.execute('INSERT INTO plan_versions VALUES(?,?,?,?,?,?)',(plan_id,version,stamp(),status,payload['symbol'],json.dumps(payload)))
            c.execute('INSERT INTO events(at,kind,symbol,reason,payload,dedupe) VALUES(?,?,?,?,?,?)',
                (stamp(),'PLAN',payload['symbol'],'人工计划已取消' if cancel else '人工计划已保存，未经自动信号确认',json.dumps(dict(plan_id=plan_id,plan_version=version,zone=payload)),f'plan:{plan_id}:{version}'))
        return plan_id,version
