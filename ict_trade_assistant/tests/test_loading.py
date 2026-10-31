import threading
import time
import pandas as pd
from desk.market_loader import MarketLoader


def test_slow_quote_does_not_block_and_is_not_duplicated():
    release=threading.Event(); started=threading.Event(); calls=[]
    def fetch(code):
        calls.append(code);started.set();release.wait(2)
        return {'health':{'quality':'UNAVAILABLE','reason':'离线测试'},'minute':pd.DataFrame(),'daily':pd.DataFrame()}
    loader=MarketLoader(fetch)
    try:
        before=time.monotonic(); result=loader.get('US.SPY',1)
        assert time.monotonic()-before<.3
        assert result['health']['quality']=='UNAVAILABLE'
        assert started.wait(.5)
        loader.clear();loader.get('US.SPY',2)
        assert calls==['US.SPY']
    finally:release.set()


def test_completed_result_reused_until_explicit_refresh():
    loader=MarketLoader(lambda code:{'health':{'quality':'UNAVAILABLE','reason':'明确断线'},'minute':pd.DataFrame(),'daily':pd.DataFrame()})
    result=loader.get('US.SPY',0)
    assert result['health']['quality']=='UNAVAILABLE'
    assert loader.get('US.SPY',0)['health']['reason']=='明确断线'
