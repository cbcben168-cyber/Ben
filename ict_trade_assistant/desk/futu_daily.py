"""Independent, versioned Futu daily snapshots. Never an Alpaca import."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3

import pandas as pd

from .clock import CAL, ET, bounds

FUTU = '最新Futu历史日K'
ORIGINAL = '原历史档案'
UPDATE = '独立更新档案'
CONTRACT = 'FUTU_OPEND/K_DAY/RTH/QFQ'
PRICE_NOTE = '事后前复权价格，含取得时已生效的后续复权；不代表回放当时实际交易价格。'
PLAN_NOTE = '人工计划保留原价；与本批前复权价格尺度未核实，暂停价格叠加与风险回报计算。'


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def utc(value):
    t = pd.Timestamp(value)
    if t.tzinfo is None:
        raise ValueError('取得及请求时间必须带时区')
    return t.tz_convert('UTC')


def _records(response, symbol, adjustment, now):
    request = response['request']
    if (request.get('symbol') != symbol or request.get('ktype') != 'K_DAY'
            or request.get('session') != 'RTH' or request.get('autype') != adjustment
            or response.get('page_complete') is not True):
        raise ValueError('Futu来源、复权、RTH或分页契约不一致')
    requested, acquired = utc(request['requested_at_utc']), utc(response['acquired_at_utc'])
    if not requested <= acquired <= now:
        raise ValueError('取得时间无效或在未来')
    expected = [str(t.date()) for t in CAL.sessions_in_range(request['start'], request['end'])]
    rows, dates = response['records'], []
    for row in rows:
        label = pd.Timestamp(row['time_key'])
        if label.tzinfo is not None or label != label.normalize() or row.get('code') != symbol:
            raise ValueError('Futu证券或纽约日K标签无效')
        day = label.date()
        if bounds(day) is None or acquired.to_pydatetime() < bounds(day)[1] + timedelta(minutes=2):
            raise ValueError('未完成日K或非交易日')
        values = [float(row[k]) for k in ('open', 'high', 'low', 'close', 'volume')]
        o, h, l, c, v = values
        if not all(math.isfinite(x) for x in values) or not (0 < l <= min(o,c) <= max(o,c) <= h and v >= 0):
            raise ValueError('无效OHLCV')
        dates.append(day.isoformat())
    if not expected or dates != expected:
        raise ValueError('交易日缺失、重复、乱序或请求覆盖不完整')
    return rows


def verify_payload(payload, now=None):
    """Reconcile *every* QFQ OHLCV against NONE plus provider actions.

    Rehab coefficients have limited precision. Rebuild dividends from the
    raw previous close and cash amount, and splits from integer ratios. Check
    against reported coefficients separately; OHLC must agree within 1e-6.
    Dividend actions never adjust volume. Unexplained changes fail closed.
    """
    now = utc(now or datetime.now(timezone.utc)) + pd.Timedelta(seconds=5)
    if payload.get('format') != 'FUTU_DAILY_V1' or payload.get('provider') != 'FUTU_OPEND':
        raise ValueError('只接收独立Futu历史记录')
    symbol = payload['symbol']
    if not symbol.startswith('US.'):
        raise ValueError('仅本次美股日K档案')
    qfq = _records(payload['responses']['QFQ'], symbol, 'QFQ', now)
    raw = _records(payload['responses']['NONE'], symbol, 'NONE', now)
    qr, nr = (payload['responses'][k]['request'] for k in ('QFQ', 'NONE'))
    if (qr['start'], qr['end']) != (nr['start'], nr['end']):
        raise ValueError('原始与复权请求区间不一致')
    rehab = payload['rehab']
    if rehab['request'].get('symbol') != symbol or rehab['request'].get('method') != 'get_rehab':
        raise ValueError('复权事件来源不一致')
    if not utc(rehab['request']['requested_at_utc']) <= utc(rehab['acquired_at_utc']) <= now:
        raise ValueError('复权事件取得时间无效')
    valuation = payload['valuation_date']
    # All three responses must share the same post-event adjustment basis.
    if any(utc(r['acquired_at_utc']).tz_convert(ET).date().isoformat() != valuation
           for r in [*payload['responses'].values(), rehab]):
        raise ValueError('复权估值日期不一致')
    actions = sorted(rehab['records'], key=lambda x:x['ex_div_date'])
    relevant = [a for a in actions if qr['start'] < a['ex_div_date'] <= valuation]
    for a in relevant:
        for k in ('forward_adj_factorA', 'forward_adj_factorB'):
            if a.get(k) is None or not math.isfinite(float(a[k])):
                raise ValueError('缺少有效复权因子')
        if float(a['forward_adj_factorA']) <= 0:
            raise ValueError('无效复权系数')
        # This ETF recovery supports cash dividends and forward/reverse splits.
        if any(a.get(k) not in (None, 0) for k in
               ('per_share_div_ratio', 'per_share_trans_ratio', 'allotment_ratio', 'stk_spo_ratio', 'spin_off_ratio')):
            raise ValueError('存在尚未验证的其他复权事件')
    raw_by_day = {r['time_key'][:10]: r for r in raw}
    factors = []
    for action in relevant:
        factor, shift = float(action['forward_adj_factorA']), float(action['forward_adj_factorB'])
        split = action.get('split_base') and action.get('split_ert')
        if split and action.get('per_cash_div'):
            raise ValueError('同日拆股及分红组合尚未验证')
        if split:
            factor = float(action['split_base'])/float(action['split_ert'])
        elif action.get('per_cash_div'):
            prior = [day for day in raw_by_day if day < action['ex_div_date']]
            if not prior:
                raise ValueError('缺少分红前原始收盘价')
            factor = 1-float(action['per_cash_div'])/float(raw_by_day[max(prior)]['close'])
        elif factor != 1 or shift != 0:
            raise ValueError('存在无法独立重建的复权事件')
        if abs(factor-float(action['forward_adj_factorA'])) > .0000101 or shift != 0:
            raise ValueError('独立重建与供应商复权系数不一致')
        factors.append((action['ex_div_date'], factor, shift))
    max_error, max_bound, max_volume_error = 0., .000001, 0.
    for q, r in zip(qfq, raw):
        if q['time_key'] != r['time_key']:
            raise ValueError('原始与复权日期不一致')
        day = q['time_key'][:10]
        events = [a for a in relevant if day < a['ex_div_date']]
        volume_factor = 1.
        for a in events:
            ratio = a.get('split_ratio')
            if ratio is not None:
                volume_factor /= float(ratio)
        for k in ('open', 'high', 'low', 'close'):
            expected = float(r[k])
            for ex_date, factor, shift in factors:
                if day < ex_date:
                    expected = expected*factor + shift
            error = abs(float(q[k])-expected)
            bound = .000001
            if error > bound:
                raise ValueError(f'{symbol} {day} {k}复权无法由供应商事件解释')
            max_error, max_bound = max(max_error,error), max(max_bound,bound)
        volume_error = abs(float(q['volume'])-float(r['volume'])*volume_factor)
        if volume_error > max(1., abs(float(r['volume'])*volume_factor)*.00000001):
            raise ValueError(f'{symbol} {day}成交量复权不一致')
        max_volume_error = max(max_volume_error, volume_error)
    if symbol == 'US.SOXX' and qr['start'] < '2026-11-05' <= qr['end']:
        split = [a for a in relevant if a['ex_div_date']=='2026-11-05'
                 and a.get('split_base')==1 and a.get('split_ert')==3]
        if len(split) != 1:
            raise ValueError('缺少SOXX 2026-11-05三拆一事件')
    return dict(symbol=symbol, contract=CONTRACT, bars=len(qfq), first=qfq[0]['time_key'][:10],
                last=qfq[-1]['time_key'][:10], valuation_date=valuation, status='PASS',
                actions=relevant, max_ohlc_error=max_error, max_ohlc_rounding_bound=max_bound,
                max_volume_error=max_volume_error, ict_eligible=False)


class FutuDailyArchive:
    """Constructors/readers never create files. Writes require our archive marker."""
    def __init__(self, path):
        self.path = Path(path).resolve()

    @classmethod
    def create(cls, path):
        archive = cls(path)
        if archive.path.name.lower() in {'history.sqlite3','updates.sqlite3','desk.sqlite3','experiments.sqlite3'}:
            raise ValueError('禁止使用受保护数据库文件名')
        archive.path.parent.mkdir(parents=True, exist_ok=True)
        with archive.path.open('xb'):
            pass
        with closing(sqlite3.connect(archive.path)) as db, db:
            db.executescript('''
                CREATE TABLE archive_contract(value TEXT PRIMARY KEY);
                INSERT INTO archive_contract VALUES('FUTU_DAILY_V1');
                CREATE TABLE captures(sha256 TEXT PRIMARY KEY, symbol TEXT, payload TEXT, verification TEXT);
                CREATE TABLE series(symbol TEXT PRIMARY KEY, contract TEXT, capture_sha TEXT);
                CREATE TABLE bars(symbol TEXT,day TEXT,qfq TEXT,raw TEXT,sha256 TEXT,capture_sha TEXT,
                                  PRIMARY KEY(symbol,day));
            ''')
        return archive

    def connect(self, write=False):
        db = sqlite3.connect(self.path.as_uri()+('?mode=rw' if write else '?mode=ro'), uri=True)
        try:
            if not write:
                db.execute('PRAGMA query_only=ON')
            if db.execute('SELECT value FROM archive_contract').fetchall() != [('FUTU_DAILY_V1',)]:
                raise ValueError('不是独立Futu档案')
        except Exception:
            db.close()
            raise
        return db

    def import_payload(self, payload):
        checked = verify_payload(payload)
        symbol, sha = payload['symbol'], digest(payload)
        basis = canonical(dict(contract=CONTRACT, valuation_date=payload['valuation_date'],
                               actions_sha=digest(payload['rehab']['records'])))
        qfq, raw = (payload['responses'][k]['records'] for k in ('QFQ','NONE'))
        rows = [(q['time_key'][:10], canonical(q), canonical(r), digest([q,r])) for q,r in zip(qfq,raw)]
        with closing(self.connect(write=True)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            first = db.execute('SELECT payload FROM captures LIMIT 1').fetchone()
            if first and json.loads(first[0])['valuation_date'] != payload['valuation_date']:
                raise ValueError('整库复权估值日期必须一致；禁止跨批次拼接')
            previous = db.execute('SELECT contract FROM series WHERE symbol=?',(symbol,)).fetchone()
            if previous and previous[0] != basis:
                raise ValueError('来源或复权基准变化，禁止拼接；必须另建档案')
            existing = dict(db.execute('SELECT day,sha256 FROM bars WHERE symbol=?',(symbol,)))
            if any(day in existing and existing[day] != row_sha for day,_,_,row_sha in rows):
                raise ValueError('同日数据冲突，整次拒绝，不覆盖历史')
            if db.execute('SELECT 1 FROM captures WHERE sha256=?',(sha,)).fetchone():
                return dict(checked, added=0, capture_sha256=sha)
            db.execute('INSERT INTO captures VALUES(?,?,?,?)',(sha,symbol,canonical(payload),canonical(checked)))
            db.executemany('INSERT OR IGNORE INTO bars VALUES(?,?,?,?,?,?)',
                           [(symbol,day,q,r,row_sha,sha) for day,q,r,row_sha in rows])
            db.execute('INSERT OR IGNORE INTO series VALUES(?,?,?)',(symbol,basis,sha))
        return dict(checked, added=sum(day not in existing for day,_,_,_ in rows), capture_sha256=sha)

    def read(self, symbol):
        with closing(self.connect()) as db:
            row = db.execute('SELECT c.sha256,c.payload,c.verification FROM series s JOIN captures c ON c.sha256=s.capture_sha WHERE s.symbol=?',(symbol,)).fetchone()
            if row is None:
                return None
            sha, encoded, checked = row
            payload = json.loads(encoded)
            if digest(payload) != sha:
                raise ValueError('供应商原始记录哈希不匹配')
            rows = db.execute('SELECT day,qfq,raw,sha256 FROM bars WHERE symbol=? ORDER BY day',(symbol,)).fetchall()
        records = []
        originals = {q['time_key'][:10]: [q,r] for q,r in zip(payload['responses']['QFQ']['records'],
                                                           payload['responses']['NONE']['records'])}
        for day,q,r,row_sha in rows:
            q, r = json.loads(q), json.loads(r)
            if digest([q,r]) != row_sha or q.get('time_key','')[:10] != day or [q,r] != originals.get(day):
                raise ValueError('行情行校验哈希不匹配')
            records.append(q)
        if len(records) != len(originals) or json.loads(checked) != verify_payload(payload):
            raise ValueError('档案覆盖或复权核验记录不一致')
        frame = pd.DataFrame(records)
        frame['ts'] = pd.to_datetime(frame.time_key).dt.tz_localize(ET).dt.tz_convert('UTC')
        frame['eligible'], frame['session'], frame['source'] = True, 'RTH', CONTRACT
        frame['finality'] = 'VENDOR_FINALITY_UNVERIFIED'
        meta = dict(json.loads(checked), source='FUTU_OPEND', feed='RTH', adjustment='QFQ',
                    acquired_at=payload['responses']['QFQ']['acquired_at_utc'],
                    requested_at=payload['responses']['QFQ']['request']['requested_at_utc'],
                    capture_sha256=sha, missing=[], price_note=PRICE_NOTE)
        return meta, frame


def attach_futu(data, archive, symbol):
    saved = archive.read(symbol)
    if saved is None:
        if symbol == 'US.VIX':
            return data
        return dict(data, futu_daily=pd.DataFrame(), futu_coverage=dict(
            symbol=symbol, source='FUTU_OPEND', feed='RTH', adjustment='QFQ', contract=CONTRACT,
            status='UNAVAILABLE', first=None, last=None, bars=0, acquired_at=None, missing=[], ict_eligible=False))
    meta, frame = saved
    return dict(data, futu_daily=frame, futu_coverage=meta)


def select_history(data, choice):
    """Select a whole series. No concatenation, minute reuse, or plan repricing."""
    if not data.get('futu_coverage'):
        return data
    if choice == FUTU and data.get('_history_selection') == FUTU:
        return data  # Preserve an already truncated replay prefix.
    original = data.get('_original_history', data)
    selected = dict(original, futu_daily=data['futu_daily'], futu_coverage=data['futu_coverage'])
    if choice != FUTU:
        return selected
    meta = data['futu_coverage']
    selected.update(_original_history=original, daily=data['futu_daily'],
                    minute=pd.DataFrame(), coverage=meta, daily_only=True, history_origin=None,
                    _price_basis_unverified=True, _history_selection=FUTU,
                    daily_snapshot_at=meta['acquired_at'],
                    _archive_dates=list(data['futu_daily'].ts.dt.tz_convert(ET).dt.date)
                        if not data['futu_daily'].empty else [])
    selected['health'] = dict(quality='UNAVAILABLE', reason='保存的前复权日K；非实时行情，1H及实时ICT资格关闭',
                              source=CONTRACT, received_at=meta['acquired_at'], right='UNKNOWN')
    # Old Alpaca independent updates stay available only with the original mode.
    selected.pop('independent_daily', None)
    selected.pop('independent_coverage', None)
    return selected
