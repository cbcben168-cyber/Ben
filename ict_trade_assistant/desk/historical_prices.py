"""Point-in-time price references and explicit missing trading-plan conditions.

Independent of observation/ICT qualification. No price here is an invented
entry, stop or profit target; user plan records are never modified.
"""
from datetime import timedelta
import math

import pandas as pd

from .clock import CAL, ET, bounds, previous_day
from .futu_hourly import hourly_prefix
from .market_state import daily_prefix, market_state


def references(daily, asof, source, coverage=None, hourly=None, hourly_meta=None):
    coverage, hourly_meta = coverage or {}, hourly_meta or {}
    result = dict(levels=[], missing=[], source=source, valuation_date=coverage.get('valuation_date'),
                  asof=pd.Timestamp(asof).isoformat(), close=None, at=None)
    frame = daily_prefix(daily, asof)
    if frame.empty:
        result['missing'].append('没有已完成日K')
        return result
    prices = frame[['open', 'high', 'low', 'close']].astype(float)
    if (frame.ts.duplicated().any() or not prices.map(math.isfinite).all().all()
            or (prices.low <= 0).any() or (prices.low > prices[['open', 'close']].min(axis=1)).any()
            or (prices.high < prices[['open', 'close']].max(axis=1)).any()
            or ('source' in frame and (frame.source.isna().any() or frame.source.nunique()!=1))):
        result['missing'].append('日K重复、混合来源或价格校验失败')
        return result
    dates = frame.ts.dt.tz_convert(ET).dt.date
    day = pd.Timestamp(asof).tz_convert(ET).date()
    result.update(close=float(frame.close.iloc[-1]), at=frame.closed_at.iloc[-1].isoformat())

    def add(name, days, method):
        subset = frame.loc[dates.isin(days)]
        if list(subset.ts.dt.tz_convert(ET).dt.date) != list(days):
            result['missing'].append(name+'：缺少完整交易日')
            return
        result['levels'].append(dict(name=name, low=float(subset.low.min()), high=float(subset.high.max()),
            from_date=str(days[0]), to_date=str(days[-1]), completed_at=subset.closed_at.iloc[-1].isoformat(),
            method=method, source=source, valuation_date=coverage.get('valuation_date'),
            capture_sha256=coverage.get('capture_sha256'), kind='HISTORICAL_REFERENCE'))

    add('前交易日', [previous_day(day)], '纽约分析日之前的一个完整RTH交易日，高低价')
    monday = day - timedelta(days=day.weekday())
    week = [s.date() for s in CAL.sessions_in_range(str(monday-timedelta(days=7)), str(monday-timedelta(days=1)))]
    if week:
        add('前一完整交易周', week, '分析日所在周之前的完整纽约交易周，逐日高低价极值')
    last = frame.ts.dt.tz_convert(ET).dt.date.iloc[-1]
    sessions = CAL.sessions_in_range(str(last-timedelta(days=50)), str(last))[-20:]
    add('最近20个已完成交易日', [s.date() for s in sessions], '截至分析时点最近20个完整RTH交易日，高低价极值')
    if hourly is not None and not hourly.empty and hourly_meta.get('status') == 'PASS':
        if coverage.get('valuation_date') != hourly_meta.get('valuation_date'):
            result['missing'].append('1H结构参考位：与日K的QFQ估值日不同，分开查看，禁止混合')
        else:
            prefix = hourly_prefix(hourly, asof)
            state, completed = market_state(prefix, '1H', asof, hourly_meta['contract'])
            if state['trend'] != 'UNKNOWN':
                # Two completed bars on BOTH sides. The pivot becomes known only
                # after the second right bar plus the unchanged quarantine.
                for column, label, compare in [('high','已确认1H摆动高点',lambda a,b:a>b),
                                                ('low','已确认1H摆动低点',lambda a,b:a<b)]:
                    for i in range(len(completed)-3, 1, -1):
                        value = float(completed[column].iloc[i])
                        neighbors = completed[column].iloc[[i-2,i-1,i+1,i+2]]
                        if all(compare(value,float(v)) for v in neighbors):
                            result['levels'].append(dict(name=label, low=value, high=value,
                                from_date=completed.ts.iloc[i].isoformat(), to_date=completed.end_at.iloc[i].isoformat(),
                                completed_at=completed.end_at.iloc[i+2].isoformat(),
                                method='左右各2根已完成1H柱的严格极值；右侧第2柱完成并隔离后才确认',
                                source=hourly_meta['contract'], valuation_date=hourly_meta['valuation_date'],
                                capture_sha256=hourly_meta['capture_sha256'], kind='HISTORICAL_REFERENCE'))
                            break
            else:
                result['missing'].append('1H结构参考位：'+state['reason'])
    else:
        result['missing'].append('1H结构参考位：尚无已验收1小时历史资料')
    return result


def target_readiness(plan, asof, basis_verified=False):
    missing = []
    if not plan:
        missing = ['实际保存的入场价格', '失效价格', '方向', '目标价格', '有效时间与周期', '价格尺度核验']
    else:
        for key, label in [('low','入场下沿'),('high','入场上沿'),('invalid','失效价格'),
                            ('target_low','用户目标下沿'),('target_high','用户目标上沿')]:
            value=plan.get(key)
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                missing.append(label)
        if plan.get('direction') not in ('LONG','SHORT'):
            missing.append('方向')
        if plan.get('status') != 'ACTIVE':
            missing.append('有效计划状态')
        if not basis_verified:
            missing.append('价格尺度核验')
        # Current persisted plan schema has no verified period/valid-until
        # contract. Saving a timestamp alone does not establish validity.
        missing.append('经核实的计划周期与有效时间')
        if not plan.get('updated_at') or pd.Timestamp(plan['updated_at']) > asof:
            missing.append('分析时点已知的计划保存时间')
    return dict(qualified=False, missing=missing, risk_reward=None, trading_eligible=False)


def focus_symbols(enabled, preference=None):
    allowed = list(dict.fromkeys(s for s in enabled if s != 'US.VIX'))
    if preference is None:
        return allowed[:15]
    return list(dict.fromkeys(s for s in preference if s in allowed))[:15]


def nearest_reference(result):
    if result['close'] is None or not result['levels']:
        return '暂无合格历史区域'
    close = result['close']
    level = min(result['levels'], key=lambda r:max(r['low']-close,close-r['high'],0))
    low, high = (str(level[key]).removesuffix('.0') for key in ('low','high'))
    return f"{level['name']} {low}–{high}"
