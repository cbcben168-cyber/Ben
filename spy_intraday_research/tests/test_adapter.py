import pandas as pd
import pytest
from spy_research.futu_quotes import QuoteReader

class Context:
    def __init__(self,replies): self.replies=iter(replies); self.tokens=[]
    def request_history_kline(self,*args,**kwargs):
        self.tokens.append(kwargs['page_req_key'])
        return next(self.replies)

def reader(replies):
    obj=object.__new__(QuoteReader)
    obj.interval=0; obj.retries=2; obj.last=0; obj.ctx=Context(replies)
    return obj

def test_pagination():
    frame=pd.DataFrame({'time_key':['2026-10-02 09:31:00']})
    second=pd.DataFrame({'time_key':['2026-10-02 09:32:00']})
    obj=reader([(0,frame,b'next'),(0,second,None)])
    assert len(obj.history('2026-10-02','2026-10-02','K_1M'))==2
    assert obj.ctx.tokens==[None,b'next']

def test_repeated_token():
    frame=pd.DataFrame({'time_key':['x']})
    obj=reader([(0,frame,b'next'),(0,frame,b'next')])
    with pytest.raises(RuntimeError,match='NO_PROGRESS'): obj.history('x','x','K_1M')

def test_permission_rejection():
    obj=reader([(-1,'permission denied',None)])
    with pytest.raises(RuntimeError,match='REJECTED'): obj.history('x','x','K_1M')

def test_no_trade_boundary():
    from pathlib import Path
    import spy_research.futu_quotes as module
    text=Path(module.__file__).read_text()
    assert 'place_order' not in text and 'OpenSecTradeContext' not in text
