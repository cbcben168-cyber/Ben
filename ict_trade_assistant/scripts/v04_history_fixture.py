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
from desk.history_source import HistorySource

SOURCE=Path(os.environ['ICT_V04_HISTORY'])
FIXED=datetime(2026,10,29,16,2,tzinfo=ET)
if not hasattr(store_module,'_V04Original'):
    store_module._V04Original=store_module.Store


class FixtureStore(store_module._V04Original):
    def __init__(self,*args,**kwargs):
        super().__init__(Path(os.environ.get('ICT_V04_DB', str(ROOT/'data/v04_acceptance/browser.sqlite3'))))

    def settings(self):
        return super().settings()


@st.cache_resource(show_spinner=False)
def snapshots():
    return HistorySource(SOURCE, FIXED)


def fetch(self,code):
    return snapshots().fetch(code)


store_module.Store=FixtureStore
provider_module.Provider.fetch=fetch
def offline_connect(self):
    raise RuntimeError('历史工作台禁止建立OpenD连接')
provider_module.Provider.connect=offline_connect
workspace_module.now_et=lambda:FIXED
st.warning('v0.4.1 本地历史工作台 · 既有真实历史快照 · 历史观察时点 2026-10-29 16:02 美东 · 非实时行情 · 无行情网络连接 · ICT实时资格关闭')
st.caption('数据模式：仅本地历史文件；OpenD订阅/历史额度检查未执行（无连接、无请求）。新增证券不会自动取得在线数据。')
runpy.run_path(str(ROOT/'app.py'),run_name='__main__')
