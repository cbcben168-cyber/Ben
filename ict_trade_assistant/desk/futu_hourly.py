"""Independent native 60M archive; end labels adapt to the frozen RTH grid.

Never attaches to ``minute`` or supplies ICT evidence. Every price remains in
the capture's post-event QFQ valuation basis, including during replay.
"""
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .clock import CAL, ET, bounds
from .futu_daily import canonical, digest, utc, verify_payload

CONTRACT = 'FUTU_OPEND/K_60M/RTH/QFQ'
MISSING = '尚无已验收1小时历史资料'


def session_grid(start, end):
    grid = []
    for day in CAL.sessions_in_range(start, end):
        opened, closed = bounds(day.date())
        for began in pd.date_range(opened, closed, freq='h', inclusive='left'):
            finished = min(began + pd.Timedelta(hours=1), pd.Timestamp(closed))
            grid.append((began.tz_convert('UTC'), finished.tz_convert('UTC')))
    return grid


def verify_hourly(payload):
    if payload.get('format') != 'FUTU_HOURLY_V1':
        raise ValueError('不是独立60分钟档案')
    # The daily companion is independently reconciled with raw DAY + actions.
    daily = payload['daily_companion']
    checked = verify_payload(daily)
    symbol, valuation = daily['symbol'], daily['valuation_date']
    if payload['symbol'] != symbol or payload['valuation_date'] != valuation:
        raise ValueError('证券或QFQ估值日不一致')
    frames = {}
    for adjustment in ('QFQ', 'NONE'):
        response = payload['responses'][adjustment]
        request = response['request']
        if (request.get('symbol'), request.get('ktype'), request.get('session'), request.get('autype')) != (
                symbol, 'K_60M', 'RTH', adjustment) or response.get('page_complete') is not True:
            raise ValueError('60分钟来源、RTH、复权或分页未通过')
        acquired = utc(response['acquired_at_utc'])
        if not utc(request['requested_at_utc']) <= acquired <= pd.Timestamp.now(tz='UTC') + pd.Timedelta(seconds=5):
            raise ValueError('60分钟请求／取得时间无效')
        if acquired.tz_convert(ET).date().isoformat() != valuation:
            raise ValueError('60分钟复权估值日不一致')
        dr = daily['responses'][adjustment]['request']
        if (request['start'], request['end']) != (dr['start'], dr['end']):
            raise ValueError('60分钟及日K验证范围不一致')
        grid = session_grid(request['start'], request['end'])
        records = response['records']
        labels = []
        for row in records:
            label = pd.Timestamp(row['time_key'])
            if label.tzinfo is not None or row.get('code') != symbol:
                raise ValueError('60分钟标签必须是纽约本地时间及同一证券')
            labels.append(label.tz_localize(ET).tz_convert('UTC'))
        if labels != [end for _, end in grid]:
            raise ValueError('60分钟结束标签缺柱、重复、乱序或不符合纽约RTH边界')
        if not grid or grid[-1][1] + timedelta(minutes=2) > acquired:
            raise ValueError('60分钟K线尚未完成2分钟确认')
        frame = pd.DataFrame(records)
        values = frame[['open', 'high', 'low', 'close', 'volume']].astype(float)
        if (not np.isfinite(values).all().all() or (values.low <= 0).any()
                or (values.volume < 0).any()
                or (values.low > values[['open', 'close']].min(axis=1)).any()
                or (values.high < values[['open', 'close']].max(axis=1)).any()):
            raise ValueError('60分钟OHLCV无效')
        frame['ts'] = pd.to_datetime([a for a, _ in grid], utc=True)
        frame['end_at'] = pd.to_datetime(labels, utc=True)
        frame['duration_minutes'] = (frame.end_at - frame.ts).dt.total_seconds() / 60
        frame['complete'], frame['eligible'], frame['session'], frame['source'] = True, True, 'RTH', CONTRACT
        # Native DAY/intraday volumes differ in observed captures; the cause is
        # unresolved. Never use DAY or 1M volume to replace native 60M volume.
        # Exact native 60M -> native DAY OHLC reconciliation verifies
        # the end-label interpretation, including the 30 minute closing candle.
        for row in daily['responses'][adjustment]['records']:
            day = row['time_key'][:10]
            group = frame.loc[frame.ts.dt.tz_convert(ET).dt.date.astype(str).eq(day)]
            actual = dict(open=group.open.iloc[0], high=group.high.max(), low=group.low.min(),
                          close=group.close.iloc[-1], volume=group.volume.sum())
            if any(abs(float(actual[k]) - float(row[k])) > 1e-6 for k in ('open', 'high', 'low', 'close')):
                raise ValueError(f'{symbol}/{day}/{adjustment}：60分钟汇总与同批日K不一致')
        frames[adjustment] = frame
    # DAY verification above establishes each day's independent corporate action
    # factor; reconcile every hourly OHLCV with that exact same day/basis.
    raw_days = {r['time_key'][:10]: r for r in daily['responses']['NONE']['records']}
    q_days = {r['time_key'][:10]: r for r in daily['responses']['QFQ']['records']}
    for q, r in zip(payload['responses']['QFQ']['records'], payload['responses']['NONE']['records']):
        day = q['time_key'][:10]
        factor = q_days[day]['close'] / raw_days[day]['close']
        volume_factor = q_days[day]['volume'] / raw_days[day]['volume'] if raw_days[day]['volume'] else 1.
        if any(abs(q[k] - r[k] * factor) > 1e-6 for k in ('open', 'high', 'low', 'close')):
            raise ValueError('60分钟QFQ无法由同日已校验复权基准解释')
        if abs(q['volume'] - r['volume'] * volume_factor) > 1.:
            raise ValueError('60分钟复权成交量不一致')
    frame = frames['QFQ']
    if len(frame) < 50:
        raise ValueError('60分钟连续历史不足50根')
    meta = dict(symbol=symbol, contract=CONTRACT, source='FUTU_OPEND', adjustment='QFQ',
                valuation_date=valuation, bars=len(frame), first=frame.ts.iloc[0].isoformat(),
                last=frame.end_at.iloc[-1].isoformat(), status='PASS', ict_eligible=False,
                timestamp_contract='纽约结束标签 → UTC开始／结束；RTH收盘截短',
                complete=True, daily_reconciliation=True, capture_sha256=digest(payload),
                volume_note='原生60M成交量；与日K或1M汇总不完全一致，原因未裁定，不互相替换',
                finality='VENDOR_FINALITY_UNVERIFIED',
                daily_verification=checked, price_note='事后前复权历史；不代表当时实际可交易价格')
    return meta, frame


class FutuHourlyArchive:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def read(self, symbol):
        manifest = json.loads((self.path/'manifest.json').read_text(encoding='utf-8'))
        entry = manifest['symbols'].get(symbol, {})
        if entry.get('status') != 'PASS':
            return dict(status='UNAVAILABLE', reason=entry.get('reason', MISSING), ict_eligible=False), pd.DataFrame()
        # A symbol-derived basename prevents manifest path traversal.
        blob = (self.path/(symbol.removeprefix('US.')+'.json')).read_bytes()
        if hashlib.sha256(blob).hexdigest() != entry['sha256']:
            raise ValueError('60分钟原始档案SHA256不匹配')
        meta, frame = verify_hourly(json.loads(blob))
        if meta['symbol'] != symbol:
            raise ValueError('60分钟档案证券与读取请求不一致')
        return meta, frame


def hourly_prefix(frame, asof):
    if frame.empty:
        return frame
    return frame.loc[frame.complete.eq(True) & frame.eligible.eq(True)
                     & (frame.end_at + pd.Timedelta(minutes=2) <= asof)].copy()


def attach_hourly(data, path, symbol):
    if not path:
        return data
    try:
        meta, frame = FutuHourlyArchive(path).read(symbol)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        meta, frame = dict(status='UNAVAILABLE', reason=str(exc), ict_eligible=False), pd.DataFrame()
    return dict(data, futu_hourly=frame, hourly_coverage=meta)
