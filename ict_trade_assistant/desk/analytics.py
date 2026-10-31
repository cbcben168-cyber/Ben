from datetime import timedelta
import math
import pandas as pd
from .clock import ET, bounds, session, overnight_day, previous_day


def normalize(raw, period, now):
    """Futu US time_key is Eastern; ambiguous DST values rejected."""
    if raw.empty:
        return pd.DataFrame(columns=['ts', 'open', 'high', 'low', 'close', 'volume', 'session', 'eligible'])
    f = raw.copy()
    f['ts'] = pd.to_datetime(f['time_key']).dt.tz_localize('America/New_York', ambiguous='raise', nonexistent='raise')
    if f.ts.duplicated().any():
        raise ValueError('Duplicate timestamps: integrity unavailable')
    f = f.sort_values('ts')
    for col in ['open', 'high', 'low', 'close', 'volume']:
        f[col] = pd.to_numeric(f[col], errors='raise')
        if not f[col].map(math.isfinite).all():
            raise ValueError('Non-finite OHLCV')
    if ((f.low > f.high) | (f.low > f[['open', 'close']].min(axis=1)) |
            (f.high < f[['open', 'close']].max(axis=1)) | (f.low <= 0) | (f.volume < 0)).any():
        raise ValueError('Invalid OHLCV')
    f['session'] = 'RTH' if period == 'DAY' else f.ts.map(session)
    if period == 'DAY':
        f['eligible'] = f.ts.map(lambda t: bool(bounds(t.date())) and now >= bounds(t.date())[1]+timedelta(minutes=2))
    else:
        # Two-minute quarantine, plus nominal close; never claims vendor finality.
        f['eligible'] = f.ts.map(lambda t: t + timedelta(minutes=3) <= now)
    f['source'] = 'FUTU_OPEND'
    f['finality'] = 'VENDOR_FINALITY_UNVERIFIED'
    return f


def window(frame, start, end):
    f = frame[(frame.ts >= start) & (frame.ts < end) & frame.eligible].copy()
    expected = pd.date_range(start, end, freq='min', inclusive='left')
    complete = len(f) == len(expected) and set(f.ts) == set(expected)
    return f, complete


def range_value(frame, start, end, now):
    f, complete = window(frame, start, end)
    ready = complete and now >= end + timedelta(minutes=2)
    return dict(status='OBSERVED_COMPLETE' if ready else 'UNAVAILABLE_INCOMPLETE',
                high=float(f.high.max()) if ready else None, low=float(f.low.min()) if ready else None,
                start=str(start), end=str(end), rows=len(f), expected=int((end-start).total_seconds()/60),
                finality='VENDOR_FINALITY_UNVERIFIED', source='FUTU_OPEND')


def key_levels(frame, day, now):
    result = {}
    b = bounds(day)
    prev = bounds(previous_day(day))
    result['PREVIOUS_RTH'] = range_value(frame[frame.session == 'RTH'], *prev, now)
    if b:
        for n in (5, 15, 30):
            result[f'OR_{n}'] = range_value(frame[frame.session == 'RTH'], b[0], b[0]+timedelta(minutes=n), now)
        start = b[0].replace(hour=4, minute=0)
        result['PRE'] = range_value(frame[frame.session == 'PRE'], start, b[0], now)
        night_start = start.replace(hour=20) - timedelta(days=1)
        result['NIGHT'] = range_value(frame[frame.session == 'NIGHT'], night_start, start, now)
    return result


def aggregate_rth(frame, minutes, now):
    records = []
    for day in sorted(set(frame.ts.dt.date)):
        b = bounds(day)
        if not b:
            continue
        start, close = b
        while start < close:
            end = min(start + timedelta(minutes=minutes), close)
            f, complete = window(frame[frame.session == 'RTH'], start, end)
            if complete and now >= end + timedelta(minutes=2):
                records.append(dict(ts=start, open=f.iloc[0].open, high=f.high.max(), low=f.low.min(),
                                    close=f.iloc[-1].close, volume=f.volume.sum(), session='RTH',
                                    duration_minutes=int((end-start).total_seconds()/60),
                                    source='DERIVED_FROM_FUTU_1M', finality='VENDOR_FINALITY_UNVERIFIED'))
            start = end
    return pd.DataFrame(records)


STAGES = ['接近流动性区域', '等待 Sweep', '等待 MSS', '等待 FVG', '价格到达关注区域', '失效']


def observe(price, quality, zone, distance_bps):
    if quality != 'AVAILABLE' or not zone:
        return 'UNAVAILABLE', '需要新鲜、权限已验证报价及人工关注区域'
    low, high = zone['low'], zone['high']
    invalid = zone.get('invalid', 0)
    if invalid and ((zone['direction'] == 'LONG' and price <= invalid) or
                    (zone['direction'] == 'SHORT' and price >= invalid)):
        return '失效', f'价格 {price:g} 穿越人工失效价 {invalid:g}'
    if low <= price <= high:
        return '价格到达关注区域', f'价格 {price:g} 位于人工区域 [{low:g}, {high:g}]'
    gap = min(abs(price-low), abs(price-high)) / price * 10000
    if gap <= distance_bps:
        return '接近流动性区域', f'距离区域 {gap:.2f} bps，阈值 {distance_bps:g} bps'
    return zone.get('stage', '等待 Sweep'), '人工 SOP 阶段；不代表自动确认 Sweep/MSS/FVG'


def previous_week_levels(daily, day, now):
    """上一已结束日历周的全部实际 RTH 交易日；缺日不回退或补值。"""
    from .clock import CAL
    monday = day - timedelta(days=day.weekday())
    start, end = monday-timedelta(days=7), monday-timedelta(days=1)
    expected = {x.date() for x in CAL.sessions_in_range(str(start), str(end))}
    result = dict(status='UNAVAILABLE_INCOMPLETE', high=None, low=None,
                  start=str(start), end=str(end), rows=0, expected=len(expected),
                  source='FUTU_OPEND_NATIVE_DAY_RTH', finality='VENDOR_FINALITY_UNVERIFIED')
    if daily.empty or not expected: return result
    f = daily[daily.ts.dt.date.isin(expected)].copy()
    result['rows'] = len(f)
    if (len(f) != len(expected) or set(f.ts.dt.date) != expected or
            not f.eligible.all() or not (f.session == 'RTH').all() or
            any(now < bounds(d)[1]+timedelta(minutes=2) for d in expected)):
        return result
    result.update(status='OBSERVED_COMPLETE', high=float(f.high.max()), low=float(f.low.min()))
    return result
