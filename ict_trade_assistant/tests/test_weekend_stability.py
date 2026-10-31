from unittest.mock import patch
from datetime import datetime,timedelta
import threading
import time
import pandas as pd
from desk.clock import ET
from desk.provider import Provider
from desk.market_loader import MarketLoader
from desk.observations import live_health


def test_opend_timeout_degrades_without_accounts_or_network():
    provider=Provider()
    with patch.object(provider,'connect',side_effect=TimeoutError('synthetic connection timeout')):
        result=provider.fetch('US.SPY')
    assert result['health']['quality']=='UNAVAILABLE'
    assert result['opend_status']=='UNAVAILABLE'
    assert result['minute'].empty and provider.connect_failures==1


def test_slow_symbol_keeps_cached_other_symbol_visible():
    release=threading.Event();started=threading.Event()
    def fetch(symbol):
        if symbol=='US.QQQ':started.set();release.wait(3);raise TimeoutError('synthetic timeout')
        return dict(health=dict(quality='AVAILABLE'),minute=pd.DataFrame({'close':[100.]}),daily=pd.DataFrame())
    loader=MarketLoader(fetch)
    try:
        loader.get('US.SPY',0);loader.jobs.join()
        loader.get('US.QQQ',0);assert started.wait(.5)
        began=time.monotonic()
        for _ in range(20):assert loader.get('US.SPY',0)['minute'].close.iloc[0]==100.
        assert time.monotonic()-began<.5
    finally:
        release.set();loader.jobs.join();loader.closed.set()


def test_quote_expires_at_90_seconds_without_new_network():
    at=datetime(2026,11,2,10,tzinfo=ET)
    h=dict(quality='AVAILABLE',quote_at=at.isoformat(),price=100.,right='LV3',server_clock_skew_seconds=0)
    assert live_health(h,at+timedelta(seconds=90))['quality']=='AVAILABLE'
    assert live_health(h,at+timedelta(seconds=90.001))['quality']=='STALE'
    assert live_health(h,at+timedelta(days=1))['quality']!='AVAILABLE'
