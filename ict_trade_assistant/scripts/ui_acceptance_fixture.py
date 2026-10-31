"""仅用于浏览器验收的离线隔离入口，绝不连接行情或真实数据库。"""
from pathlib import Path
import sys, runpy
from unittest.mock import patch
from datetime import datetime
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import desk.store as store_module
if not hasattr(store_module,"_FixtureOriginal"):
    store_module._FixtureOriginal=store_module.Store
Store=store_module._FixtureOriginal
from desk.clock import ET
from desk.analytics import normalize
FIXED=datetime(2026,10,29,11,10,tzinfo=ET)
class FixtureStore(Store):
    def __init__(self,*a,**kw): super().__init__(ROOT/'data/ui_acceptance/fixture.sqlite3')
    def settings(self):
        s=super().settings();s['watchlist']=['US.SPY','US.QQQ','US.IWM','US.SOXX','US.DIA'];s['refresh_seconds']=3
        s['zones']={c:dict(low=99.+i*100,high=101.+i*100,invalid=98.+i*100,direction='LONG',stage='等待 MSS') for i,c in enumerate(s['watchlist'])}
        return s

def fetch(self,code):
    i=['US.SPY','US.QQQ','US.IWM','US.SOXX','US.DIA','US.VIX'].index(code)
    base=100.+i*100
    frames=[]
    for d in pd.bdate_range('2026-10-19','2026-10-29'):
        ts=pd.date_range(str(d.date())+' 09:30',periods=390,freq='min')
        f=pd.DataFrame(dict(time_key=ts.astype(str),open=base,high=base+1,low=base-1,close=base+.2,volume=10.))
        frames.append(f)
    minute=normalize(pd.concat(frames,ignore_index=True),'1M',FIXED)
    ds=pd.bdate_range('2026-10-01','2026-10-28')
    daily=normalize(pd.DataFrame(dict(time_key=ds.astype(str),open=base,high=base+2,low=base-2,close=base+.2,volume=100.)),'DAY',FIXED)
    return dict(health=dict(quality='AVAILABLE',price=base,reason='离线合成数据，仅用于界面验收',quote_at=FIXED.isoformat(),received_at=FIXED.isoformat(),source='离线合成验收数据',right='UNKNOWN'),minute=minute,daily=daily,errors=[])
st.warning('离线合成界面验收 · 非实时行情 · 独立测试数据库 · 不可用于交易')
import desk.provider as provider_module
import desk.workspace as workspace_module
store_module.Store=FixtureStore
provider_module.Provider.fetch=fetch
workspace_module.now_et=lambda:FIXED
runpy.run_path(str(ROOT/'app.py'),run_name='__main__')
