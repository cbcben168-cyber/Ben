"""Point-in-time historical market description, independent of ICT."""
from datetime import timedelta

import numpy as np
import pandas as pd

from .clock import CAL, bounds


RULES = (
    "至少50根连续且已完成的同源K线。EMA20/50使用最近50根收盘递推（首根初始化）；"
    "ATR14为14根真实波幅的算术均值。比较前后两个不重叠的5柱窗口高点和低点。"
    "收盘>EMA20>EMA50且高低点均抬升为上涨；严格反向为下跌。"
    "两EMA价差≤0.5 ATR且两个窗口的高点差和低点差均≤1 ATR为横盘；其他为过渡。"
    "ATR14/收盘与此前20柱该比例的中位数相比，≥1.25为高波动，≤0.8为低波动，其余正常。"
    "缺柱、重复、非法OHLC、来源不明或历史不足时为UNKNOWN。仅描述历史环境。"
)


def daily_prefix(frame, asof):
    """Daily timestamps are session labels, not publication or close times."""
    if frame.empty:
        return frame
    frame = frame.loc[frame.ts <= asof].copy()
    closes = {day: bounds(day) for day in frame.ts.dt.date.unique()}
    frame['closed_at'] = frame.ts.map(
        lambda ts: closes[ts.date()][1] if closes[ts.date()] else pd.NaT
    )
    return frame.loc[frame.eligible.eq(True) & frame.closed_at.notna()
                     & (frame.closed_at + timedelta(minutes=2) <= asof)].sort_values('ts')


def market_state(frame, period, asof, source):
    if period == '1D':
        frame = daily_prefix(frame, asof)
    elif not frame.empty:
        frame = frame.assign(closed_at=frame.ts + pd.to_timedelta(frame.duration_minutes, unit='min'))
        frame = frame.loc[frame.closed_at + timedelta(minutes=2) <= asof].sort_values('ts')
    state = dict(trend='UNKNOWN', volatility='UNKNOWN', bars=len(frame), analysis_asof=asof,
                 period=period, source=source, at=None, close=None)
    if frame.empty:
        return state, frame
    state.update(at=frame.closed_at.iloc[-1], close=float(frame.close.iloc[-1]))
    if len(frame) < 50 or source in (None, '', 'UNKNOWN', 'UNAVAILABLE'):
        return state, frame
    sample = frame.tail(50)
    if period == '1D':
        expected = [x.date() for x in CAL.sessions_in_range(
            str(sample.ts.iloc[0].date()), str(sample.ts.iloc[-1].date()))]
        actual = list(sample.ts.dt.date)
    else:
        expected = []
        for session in CAL.sessions_in_range(str(sample.ts.iloc[0].date()), str(sample.ts.iloc[-1].date())):
            start, end = bounds(session.date())
            expected.extend(pd.date_range(start, end, freq='h', inclusive='left'))
        expected = [x for x in expected if sample.ts.iloc[0] <= x <= sample.ts.iloc[-1]]
        actual = list(sample.ts)
    ohlc = sample[['open', 'high', 'low', 'close']]
    if (actual != expected or not np.isfinite(ohlc).all().all()
            or (sample.low <= 0).any()
            or (sample.low > sample[['open', 'close']].min(axis=1)).any()
            or (sample.high < sample[['open', 'close']].max(axis=1)).any()):
        return state, frame
    close = sample.close
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    tr = pd.concat([sample.high-sample.low, (sample.high-close.shift()).abs(),
                    (sample.low-close.shift()).abs()], axis=1).max(axis=1)
    atrs = tr.rolling(14).mean()
    atr = atrs.iloc[-1]
    atr_pct = atrs / close
    baseline = atr_pct.iloc[-21:-1].median()
    prior, recent = sample.iloc[-10:-5], sample.tail(5)
    high_delta = recent.high.max() - prior.high.max()
    low_delta = recent.low.min() - prior.low.min()
    last = close.iloc[-1]
    trend = '过渡'
    if last > ema20 > ema50 and high_delta > 0 and low_delta > 0:
        trend = '上涨'
    elif last < ema20 < ema50 and high_delta < 0 and low_delta < 0:
        trend = '下跌'
    elif abs(ema20-ema50) <= .5*atr and max(abs(high_delta), abs(low_delta)) <= atr:
        trend = '横盘'
    ratio = atr_pct.iloc[-1]/baseline if baseline > 0 else None
    volatility = 'UNKNOWN' if ratio is None else '高' if ratio >= 1.25 else '低' if ratio <= .8 else '正常'
    state.update(trend=trend, volatility=volatility, ema20=ema20, ema50=ema50, atr14=atr,
                 atr_fraction=atr_pct.iloc[-1], volatility_baseline=baseline, volatility_ratio=ratio,
                 high_delta=high_delta, low_delta=low_delta, sample_from=sample.closed_at.iloc[0])
    return state, frame
