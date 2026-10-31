import pytest

@pytest.fixture
def market_fixture():
    from datetime import datetime
    import pandas as pd
    from desk.clock import ET, CAL
    from desk.analytics import normalize
    now=datetime(2026,10,30,10,10,tzinfo=ET)
    minute_times=pd.date_range('2026-10-29 09:30',periods=390,freq='min').append(pd.date_range('2026-10-30 09:30',periods=38,freq='min'))
    daily_times=CAL.sessions_in_range('2026-10-01','2026-10-29').tz_localize(None)
    def frame(ts,period):
        return normalize(pd.DataFrame(dict(time_key=ts.astype(str),open=100.,high=102.,low=98.,close=100.,volume=10.)),period,now)
    return dict(health=dict(quality='AVAILABLE',price=100.,quote_at=now.isoformat(),received_at=now.isoformat(),
                           right='LV3',source='SYNTHETIC_TEST_ONLY',reason='隔离合成测试'),
                minute=frame(minute_times,'1M'),daily=frame(daily_times,'DAY'),errors=[])

@pytest.fixture(autouse=True)
def isolated_streamlit_resources(monkeypatch):
    import streamlit as st
    import logging
    monkeypatch.setattr('desk.diagnostics.initialize',lambda root:logging.getLogger('ict.test'))
    st.cache_resource.clear()
    yield
    st.cache_resource.clear()
