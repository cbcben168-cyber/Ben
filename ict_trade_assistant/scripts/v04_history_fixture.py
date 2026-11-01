"""真实历史快照隔离浏览器入口；无网络，绝不打开原数据库。"""
from pathlib import Path
import json
import os
import runpy
import sys
from datetime import datetime
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desk.clock import ET
import desk.store as store_module
import desk.provider as provider_module
import desk.workspace as workspace_module

SOURCE=Path(os.environ['ICT_V04_HISTORY'])
FIXED=datetime(2026,10,29,16,2,tzinfo=ET)
if not hasattr(store_module,'_V04Original'):
    store_module._V04Original=store_module.Store


class FixtureStore(store_module._V04Original):
    def __init__(self,*args,**kwargs):
        super().__init__(ROOT/'data/v04_acceptance/browser.sqlite3')

    def settings(self):
        return dict(super().settings(),refresh_seconds=3)


@st.cache_resource(show_spinner=False)
def snapshots():
    saved=json.loads(SOURCE.read_text(encoding='utf-8'))
    for item in saved.values():
        for period in ('minute','daily'):
            item[period]=pd.DataFrame(item[period])
            if not item[period].empty:
                item[period]['ts']=pd.to_datetime(item[period].ts,utc=True).dt.tz_convert(ET)
    return saved


def fetch(self,code):
    import copy
    if code not in snapshots():
        return dict(health=dict(quality='UNAVAILABLE',reason='历史快照未提供VIX',received_at=FIXED.isoformat()),minute=pd.DataFrame(),daily=pd.DataFrame(),errors=[])
    value=copy.deepcopy(snapshots()[code])
    value['health'].update(quality='STALE',reason='既有真实历史快照；非实时行情')
    return value


store_module.Store=FixtureStore
provider_module.Provider.fetch=fetch
workspace_module.now_et=lambda:FIXED
st.warning('v0.4独立离线验收 · 既有真实历史快照 · 时间固定于2026-10-29 · 无行情网络连接 · 非实时市场通过')
runpy.run_path(str(ROOT/'app.py'),run_name='__main__')
