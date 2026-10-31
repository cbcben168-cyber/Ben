"""关键价格观察；只描述距离，不确认 ICT 结构或许可入场。"""
from datetime import timedelta
import hashlib
import json
import math
import pandas as pd
from .clock import ET, CAL, bounds, previous_day, session
from .analytics import key_levels, previous_week_levels, window

VERSION = 'OBSERVATION_V021_1'
SYMBOLS = ('US.SPY', 'US.QQQ', 'US.IWM', 'US.SOXX')
PRIORITY = {'MANUAL': 0, 'PDH': 1, 'PDL': 1, 'PWH': 2, 'PWL': 2,
            'OR_5_HIGH': 3, 'OR_5_LOW': 3, 'OR_15_HIGH': 3,
            'OR_15_LOW': 3, 'OR_30_HIGH': 3, 'OR_30_LOW': 3}


def parameter_version(settings):
    payload = dict(version=VERSION, atr_period=14, max_atr=settings.get('candidate_atr', .25),
                   zones=settings.get('zones', {}), priority=PRIORITY)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def context(now):
    now = now.astimezone(ET)
    b = bounds(now.date())
    completed = now.date() if b and now >= b[1] else previous_day(now.date())
    target = now.date() if b and now < b[1] else CAL.next_session(pd.Timestamp(completed)).date()
    return dict(mode='LIVE' if session(now) == 'RTH' else 'PREPARATION',
                trading_day=str(target), reference_day=str(completed))


def live_health(health, now):
    """缓存每次展示时重验；闭市与跨交易日的 AVAILABLE 也不能继续实时使用。"""
    h = health.copy()
    if h.get('quality') != 'AVAILABLE':
        return h
    try:
        ts = pd.Timestamp(h['quote_at'])
        age = (now-ts).total_seconds()
        if (ts.tzinfo is None or not math.isfinite(float(h['price'])) or float(h['price']) <= 0
                or age < -5 or abs(h.get('server_clock_skew_seconds', 0)) > 5
                or h.get('right') not in ('LV1', 'LV2', 'LV3')):
            raise ValueError('报价、权限或时钟检查失败')
        if age > 90:
            h.update(quality='STALE', reason='缓存报价超过 90 秒')
        elif session(now) != 'RTH' or session(ts) != 'RTH' or ts.astimezone(ET).date() != now.astimezone(ET).date():
            h.update(quality='UNAVAILABLE', reason='当前不在已验证的实时 RTH 监控时段')
    except (KeyError, TypeError, ValueError):
        h.update(quality='UNAVAILABLE', reason='报价、权限或时钟证据不完整')
    return h


def atr_value(daily, last_day):
    """14 个真实波幅，需要连续15个完整原生日柱，不用分钟替代或跨缺口拼接。"""
    if daily.empty:
        return None
    sessions = CAL.sessions_window(pd.Timestamp(last_day), -15)
    expected = {x.date() for x in sessions}
    f = daily[daily.ts.dt.date.isin(expected)].sort_values('ts')
    if (len(f) != 15 or set(f.ts.dt.date) != expected or not f.eligible.all()
            or not (f.session == 'RTH').all()):
        return None
    prev = f.close.shift()
    tr = pd.concat([f.high-f.low, (f.high-prev).abs(), (f.low-prev).abs()], axis=1).max(axis=1)
    value = float(tr.iloc[1:].mean())
    return value if math.isfinite(value) and value > 0 else None


def build_observation(symbol, data, settings, now, zone=None):
    ctx = context(now)
    h = live_health(data['health'], now)
    minute, daily = data['minute'], data['daily']
    day = pd.Timestamp(ctx['reference_day']).date()
    target = pd.Timestamp(ctx['trading_day']).date()
    result = dict(symbol=symbol, **ctx, status='UNAVAILABLE', levels={}, candidates=[], monitors=[],
                  health=h, calculation_version=VERSION, parameter_version=parameter_version(dict(settings, zones={**settings.get('zones',{}),symbol:zone}) if zone else settings),
                  reason='没有已验证完整的最近 RTH 数据', source='FUTU_OPEND',
                  finality='VENDOR_FINALITY_UNVERIFIED', evaluated_at=now.isoformat())
    result['history_snapshots']={p:data.get(p+'_snapshot_at') for p in ('minute','daily')}
    result['retained_periods']=data.get('retained_periods',[])
    result['opend_status']=data.get('opend_status','UNKNOWN')
    levels = key_levels(minute, target, now) if not minute.empty else {}
    levels['PREVIOUS_WEEK'] = previous_week_levels(daily, target, now)
    # 准备模式展示最近已结束 RTH 的 OR，明确标注日期，不冒充下一交易日 OR。
    if ctx['mode'] == 'PREPARATION' and not minute.empty:
        recent = key_levels(minute, day, now)
        levels.update({k: dict(v, historical_day=str(day)) for k, v in recent.items() if k.startswith('OR_')})
    result['levels'] = levels
    atr = atr_value(daily, day)
    result['atr'] = atr
    result['atr_day'] = str(day)
    reference = None
    if not minute.empty:
        f, complete = window(minute[minute.session == 'RTH'], *bounds(day))
        if complete and now >= bounds(day)[1]+timedelta(minutes=2):
            native = daily[daily.ts.dt.date == day] if not daily.empty else daily
            if (len(native)==1 and bool(native.iloc[0].eligible) and native.iloc[0].session=='RTH'
                    and math.isclose(float(native.iloc[0].high),float(f.high.max()),abs_tol=1e-6)
                    and math.isclose(float(native.iloc[0].low),float(f.low.min()),abs_tol=1e-6)):
                reference = float(native.iloc[0].close)
                result['close_verification']=dict(native_daily_close=reference,last_minute_close=float(f.iloc[-1].close),
                                                  native_daily_bar_at=native.iloc[0].ts.isoformat(),
                                                  native_daily_close_at=bounds(day)[1].isoformat(),
                                                  last_minute_bar_at=f.iloc[-1].ts.isoformat(),
                                                  last_minute_close_at=(f.iloc[-1].ts+timedelta(minutes=1)).isoformat(),
                                                  resolution='UNRESOLVED',
                                                  rth_minutes=len(f),high_low_match=True,
                                                  note='原生日线收盘价；不把最后一分钟收盘冒充日线收盘')
    real = ctx['mode'] == 'LIVE' and h['quality'] == 'AVAILABLE'
    if ctx['mode'] == 'LIVE' and not real:
        result['mode'] = 'HISTORICAL_ONLY'
    price = float(h['price']) if real else reference
    result.update(reference_price=price, reference_at=h.get('quote_at') if real else str(bounds(day)[1]),
                  distance_basis='实时 RTH 报价' if real else 'Futu 原生日 K 收盘价（历史距离，非实时）',
                  source=h.get('source') if real else 'FUTU_OPEND / native DAY RTH close + complete 1M verification')
    if price is None or atr is None:
        result['reason'] = '最近完整 RTH 收盘价不可用' if price is None else 'ATR 所需连续15个完整日柱不足'
        return result
    result.update(status='AVAILABLE', reason='实时价格检查通过' if real else '历史准备可用；实时入场审查关闭')
    keys = []
    for name, value in levels.items():
        if value.get('status') != 'OBSERVED_COMPLETE':
            continue
        for side in ('high', 'low'):
            label = ({'PREVIOUS_RTH': ('PDH', 'PDL'), 'PREVIOUS_WEEK': ('PWH', 'PWL')}.get(name)
                     or (name+'_HIGH', name+'_LOW'))[side == 'low']
            if name not in ('PREVIOUS_RTH', 'PREVIOUS_WEEK') and not name.startswith('OR_'):
                continue
            keys.append((label, value[side], value[side], 'UNKNOWN', value))
    if zone:
        keys.append(('MANUAL', zone['low'], zone['high'], zone.get('direction', 'UNKNOWN'),
                     dict(source='USER_MANUAL', start=str(target), end=str(target))))
    for label, low, high, direction, evidence in keys:
        if not all(math.isfinite(float(x)) and x > 0 for x in (low, high)) or high < low:
            continue
        gap = max(low-price, price-high, 0)
        distance = gap/atr
        state = 'INSIDE' if low <= price <= high else 'NEAR' if distance <= settings.get('candidate_atr', .25) else 'OUTSIDE'
        next_action = '等待人工复核；关键价位距离不代表ICT结构确认，请独立核对1H历史事件'
        row = dict(symbol=symbol, key=label, low=low, high=high, price=price,
                   gap=gap, atr_distance=distance, atr=atr, direction=direction, state=state,
                   reason=f'{label} · '+('进入关键价格区域' if state == 'INSIDE' else '接近关键价格' if state == 'NEAR' else '离开关注范围'),
                   next_action=next_action, mode=result['mode'], source=result['source'],
                   quote_at=result['reference_at'], trading_day=ctx['trading_day'],
                   reference_day=ctx['reference_day'], calculation_version=VERSION,
                   parameter_version=result['parameter_version'], level_source=evidence.get('source'),
                   level_start=evidence.get('start'), level_end=evidence.get('end'),
                   historical_day=evidence.get('historical_day'), distance_basis=result['distance_basis'],
                   valid_until=str(bounds(target)[1]) if not real else str(pd.Timestamp(h['quote_at'])+timedelta(seconds=90)),
                   priority=PRIORITY.get(label, 99), finality='VENDOR_FINALITY_UNVERIFIED')
        result['monitors'].append(row)
        if state != 'OUTSIDE':
            result['candidates'].append(row)
    return result


def regions(observation):
    """闭区间有交集（含端点相等）才合并；不设价格容差，不修改原始记录。"""
    groups = []
    for row in sorted(observation['monitors'], key=lambda r: (r['low'], r['high'], r['key'])):
        if groups and row['low'] <= groups[-1]['high']:
            groups[-1]['high'] = max(groups[-1]['high'], row['high'])
            groups[-1]['members'].append(row)
        else:
            groups.append(dict(low=row['low'], high=row['high'], members=[row]))
    result = []
    for group in groups:
        members = sorted(group['members'], key=lambda r: (r['priority'], r['key']))
        row = dict(members[0])
        low, high = group['low'], group['high']
        gap = max(low-row['price'], row['price']-high, 0)
        row.update(low=low, high=high, gap=gap, atr_distance=gap/row['atr'],
                   keys=[m['key'] for m in members], members=members,
                   state='INSIDE' if gap == 0 else 'NEAR' if any(m['state']=='NEAR' for m in members) else 'OUTSIDE')
        row['region_label'] = ' / '.join(row['keys'])
        result.append(row)
    return sorted(result, key=lambda r: (r['atr_distance'], r['priority'], r['key']))


def ranked(observations):
    rows = []
    for symbol, observation in observations.items():
        if symbol not in SYMBOLS:
            continue
        eligible = [r for r in regions(observation) if r['state'] != 'OUTSIDE']
        if eligible:
            rows.append(eligible[0])
    return sorted(rows, key=lambda r: (r['atr_distance'], r['priority'], r['symbol'], r['key']))


def price_basis_comparison(observations, max_atr=.25):
    """相同原始价位及 ATR 下比较两种历史口径，含候选门槛变化。"""
    by_basis = {}
    for basis in ('native_daily_close', 'last_minute_close'):
        rows = []
        for symbol, o in observations.items():
            price = o.get('close_verification', {}).get(basis)
            if symbol not in SYMBOLS or price is None or not o.get('atr') or not o['monitors']:
                continue
            r = min(o['monitors'], key=lambda r: (max(r['low']-price, price-r['high'], 0)/o['atr'], r['priority'], r['key']))
            distance = max(r['low']-price, price-r['high'], 0)/o['atr']
            rows.append(dict(symbol=symbol, price=price, key=r['key'], distance=distance, candidate=distance<=max_atr))
        rows.sort(key=lambda r: (r['distance'], PRIORITY.get(r['key'],99), r['symbol'], r['key']))
        by_basis[basis] = {r['symbol']:dict(r, rank=n) for n,r in enumerate(rows,1)}
    return [dict(证券=s, 日K收盘=a['price'], 末分钟收盘=b['price'],
                 日K名次=a['rank'], 末分钟名次=b['rank'], 名次变化=b['rank']-a['rank'],
                 日K距离ATR=a['distance'], 末分钟距离ATR=b['distance'],
                 日K关注价位=a['key'], 末分钟关注价位=b['key'],
                 日K进入候选=a['candidate'], 末分钟进入候选=b['candidate'])
            for s,a in by_basis['native_daily_close'].items()
            if (b := by_basis['last_minute_close'].get(s))]


def record_events(store, observation):
    """历史准备永远不写实时到价事件，系统健康独立保存。"""
    h = observation['health']
    store.transition('SYSTEM', observation['symbol'], 'DATA_HEALTH', h['quality'],
                     observation['evaluated_at'], h['reason'], h, 'health')
    if observation['mode'] != 'LIVE' or observation['status'] != 'AVAILABLE':
        return
    for row in observation['monitors']:
        scope = row['trading_day']+':'+row['parameter_version']+f":{row['low']}:{row['high']}"
        store.transition('MARKET', row['symbol'], row['key'], row['state'], row['quote_at'],
                         row['reason'], row, scope)
