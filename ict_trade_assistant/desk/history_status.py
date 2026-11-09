"""Presentation-only period freshness; never changes archive qualification."""
import pandas as pd

from .clock import ET
from .daily_update import latest_completed

SCALE_WARNING = '价格尺度未获统一认证；不跨周期叠加、合并参考价或计算可执行风险回报；实时资格关闭。'


def period_status(state, coverage, asof, label, source):
    coverage = coverage or {}
    at = state.get('at')
    completed = pd.Timestamp(at).tz_convert(ET) if at is not None else None
    expected = latest_completed(asof)
    stale = completed is not None and str(completed.date()) < expected
    rejected = coverage.get('status') in ('UNAVAILABLE', 'REJECTED', 'FAIL')
    usable = state.get('trend', 'UNKNOWN') != 'UNKNOWN' and not rejected
    status = 'REJECTED' if rejected else 'MISSING' if completed is None else 'STALE' if stale else 'PASS' if usable else 'INSUFFICIENT'
    description = (label+'资料不合格' if rejected else label+'历史资料已过期' if stale else
                   label+'合格（仅历史）' if usable else label+'资料不足或未验收')
    return dict(label=label, completed_at=completed.isoformat() if completed is not None else None,
                completed_text=completed.strftime('%Y-%m-%d %H:%M 纽约') if completed is not None else '无已验收资料',
                source=coverage.get('contract') or source or '未提供',
                valuation_date=coverage.get('valuation_date') or '未提供', expected_day=expected,
                status=status, description=description, stale=stale, close=state.get('close'),
                qualified_history=usable and not stale,
                reason=coverage.get('reason') or (state.get('reason') if not usable else ''),
                trading_eligible=False)


def period_pair(daily_state, hourly_state, daily_meta, hourly_meta, asof, daily_source, hourly_source):
    day = period_status(daily_state, daily_meta, asof, '日K', daily_source)
    hour = period_status(hourly_state, hourly_meta, asof, '1H', hourly_source)
    # Missing basis evidence never becomes cross-period certification. Older
    # workspaces with no independent hourly source keep their existing behavior.
    cross_scale_blocked = bool(hourly_meta and daily_meta and (
        not daily_meta.get('valuation_date') or not hourly_meta.get('valuation_date') or
        daily_meta['valuation_date'] != hourly_meta['valuation_date'] or
        daily_meta.get('source') != hourly_meta.get('source')))
    return dict(daily=day, hourly=hour, cross_scale_blocked=cross_scale_blocked,
                scale_notice=SCALE_WARNING if cross_scale_blocked else '',
                executable_risk_reward=None, trading_eligible=False)
