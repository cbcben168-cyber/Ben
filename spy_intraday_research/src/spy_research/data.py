"""Calendar-aware normalization. Never fill missing market prices."""
import pandas as pd
import exchange_calendars as xc

PRICE = ['open', 'high', 'low', 'close']

def schedule(start, end):
    cal = xc.get_calendar('XNYS')
    return cal.schedule.loc[start:end]

def normalize(raw, semantics='start', minutes=1):
    frame = raw.copy()
    frame['ts_start_utc'] = pd.to_datetime(frame.time_key).dt.tz_localize(
        'America/New_York', ambiguous='raise', nonexistent='raise').dt.tz_convert('UTC')
    if semantics == 'end':
        frame['ts_start_utc'] -= pd.Timedelta(minutes=minutes)
    elif semantics != 'start':
        raise ValueError('UNKNOWN_TIMESTAMP_SEMANTICS')
    frame['ts_end_utc'] = frame.ts_start_utc + pd.Timedelta(minutes=minutes)
    frame['session_date'] = frame.ts_start_utc.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    keys = ['code', 'ts_start_utc']
    values = PRICE + ['volume'] + (['turnover'] if 'turnover' in frame else [])
    frame[values] = frame[values].apply(pd.to_numeric, errors='coerce')
    for _, group in frame.groupby(keys):
        if len(group[values].drop_duplicates()) > 1:
            raise ValueError('CONFLICTING_DUPLICATE')
    return frame.drop_duplicates(keys).sort_values('ts_start_utc').reset_index(drop=True)

def quality(frame, start, end):
    rows, accepted = [], []
    calendar = schedule(start, end)
    for day, session in calendar.iterrows():
        date = day.strftime('%Y-%m-%d')
        expected = pd.date_range(session.open, session.close, freq='min', inclusive='left')
        chunk = frame[frame.session_date == date].copy()
        actual = pd.DatetimeIndex(chunk.ts_start_utc)
        numeric = chunk[PRICE + ['volume']].apply(pd.to_numeric, errors='coerce')
        finite = numeric.notna().all(axis=1) & (numeric.abs() != float('inf')).all(axis=1)
        valid = finite & (numeric[PRICE] > 0).all(axis=1) & (numeric.volume >= 0)
        valid &= (numeric.low <= numeric[['open', 'close']].min(axis=1))
        valid &= (numeric.high >= numeric[['open', 'close']].max(axis=1))
        valid &= numeric.low <= numeric.high
        missing, extra = len(expected.difference(actual)), len(actual.difference(expected))
        reasons = []
        if missing: reasons.append('MISSING_MINUTES')
        if extra: reasons.append('EXTRA_MINUTES')
        if (~valid).any(): reasons.append('INVALID_OHLCV')
        if actual.duplicated().any(): reasons.append('DUPLICATE')
        rows.append(dict(session_date=date, expected=len(expected), actual=len(chunk),
                         missing=missing, extra=extra, invalid=int((~valid).sum()),
                         status='QUARANTINE' if reasons else 'PASS', reason=';'.join(reasons)))
        if not reasons: accepted.append(chunk)
    outside = set(frame.session_date) - {d.strftime('%Y-%m-%d') for d in calendar.index}
    for date in sorted(outside):
        rows.append(dict(session_date=date, expected=0, actual=int((frame.session_date == date).sum()),
                         missing=0, extra=int((frame.session_date == date).sum()), invalid=0,
                         status='QUARANTINE', reason='NON_SESSION_DATE'))
    good = pd.concat(accepted, ignore_index=True) if accepted else frame.iloc[:0].copy()
    return good, pd.DataFrame(rows)

def aggregate5(frame):
    rows = []
    for date, chunk in frame.groupby('session_date', sort=True):
        chunk = chunk.sort_values('ts_start_utc')
        for pos in range(0, len(chunk), 5):
            block = chunk.iloc[pos:pos+5]
            if len(block) != 5 or not (block.ts_start_utc.diff().dropna() == pd.Timedelta(minutes=1)).all():
                raise ValueError('INCOMPLETE_5M_BLOCK')
            row = dict(code=block.code.iloc[0], session_date=date,
                       ts_start_utc=block.ts_start_utc.iloc[0], ts_end_utc=block.ts_end_utc.iloc[-1],
                       open=block.open.iloc[0], high=block.high.max(), low=block.low.min(),
                       close=block.close.iloc[-1], volume=block.volume.sum())
            if 'turnover' in block: row['turnover'] = block.turnover.sum(min_count=5)
            rows.append(row)
    return pd.DataFrame(rows, columns=['code','session_date','ts_start_utc','ts_end_utc',*PRICE,'volume','turnover'])
