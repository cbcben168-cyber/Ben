from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
import exchange_calendars as xc
import pandas as pd

ET = ZoneInfo('America/New_York')
UTC = ZoneInfo('UTC')
CAL = xc.get_calendar('XNYS')


def now_et():
    return datetime.now(ET)


def bounds(day):
    """Return actual scheduled RTH bounds; out-of-calendar fails closed."""
    label = pd.Timestamp(day)
    if not CAL.is_session(label):
        return None
    return (CAL.session_open(label).tz_convert(ET).to_pydatetime(),
            CAL.session_close(label).tz_convert(ET).to_pydatetime())


def previous_day(day):
    return CAL.date_to_session(pd.Timestamp(day) - pd.Timedelta(days=1), direction='previous').date()


def session(ts):
    ts = ts.astimezone(ET)
    b = bounds(ts.date())
    t = ts.time().replace(tzinfo=None)
    if b and b[0] <= ts < b[1]:
        return 'RTH'
    if b and time(4) <= t < time(9, 30):
        return 'PRE'
    if b and b[1].time() == time(16) and time(16) <= t < time(20):
        return 'AFTER'
    # Vendor overnight clock bucket, eligibility not exchange-calendar verified.
    if t >= time(20) or t < time(4):
        return 'NIGHT'
    return 'UNKNOWN'


def overnight_day(ts):
    ts = ts.astimezone(ET)
    return ts.date() + timedelta(days=1) if ts.hour >= 20 else ts.date()
