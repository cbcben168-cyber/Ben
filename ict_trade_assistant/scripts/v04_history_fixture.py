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
from desk.history_runtime import activate_config
try:
    HISTORY_CONFIG = activate_config(ROOT)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
from desk.clock import ET
import desk.store as store_module
import desk.provider as provider_module
import desk.workspace as workspace_module
from desk.history_source import HistorySource
from desk.history_import import DailyArchive
from desk.futu_daily import FutuDailyArchive, attach_futu
from desk.futu_update import FutuVersions
from desk.futu_hourly import attach_hourly

SOURCE=Path(os.environ['ICT_V04_HISTORY'])
FIXED=datetime(2026,10,29,16,2,tzinfo=ET)
FUTU_PATH=os.environ.get('ICT_FUTU_DAILY_ARCHIVE')
FUTU_VERSIONS=FutuVersions(FUTU_PATH, os.environ.get('ICT_FUTU_DAILY_ROOT')) if FUTU_PATH else None
UPDATE_ROOT=Path(os.environ.get('ICT_DAILY_UPDATE_ROOT',str(ROOT/'data/v043')))
if not hasattr(store_module,'_V04Original'):
    store_module._V04Original=store_module.Store


class FixtureStore(store_module._V04Original):
    def __init__(self,*args,**kwargs):
        super().__init__(Path(os.environ.get('ICT_V04_DB', str(ROOT/'data/v04_acceptance/browser.sqlite3'))))

    def settings(self):
        return super().settings()


@st.cache_resource(show_spinner=False)
def snapshots():
    return HistorySource(SOURCE, FIXED, DailyArchive(Path(os.environ.get('ICT_DAILY_ARCHIVE',str(ROOT/'data/v042/history.sqlite3')))),
                         DailyArchive(UPDATE_ROOT/'updates.sqlite3'))


def fetch(self,code):
    value=snapshots().fetch(code)
    if not FUTU_VERSIONS:
        return value
    path, version = FUTU_VERSIONS.current()
    result = attach_futu(value, FutuDailyArchive(path), code)
    if result.get('futu_coverage'):
        result['futu_coverage']['archive_version'] = version
    return attach_hourly(result, os.environ.get('ICT_FUTU_HOURLY_ARCHIVE'), code)


store_module.Store=FixtureStore
provider_module.Provider.fetch=fetch
provider_module.Provider.history_revision=lambda self,code:(snapshots().revision(code),
    (FUTU_VERSIONS.current()[1], FUTU_VERSIONS.pointer.stat().st_mtime_ns if FUTU_VERSIONS.pointer.exists() else 0)
    if FUTU_VERSIONS else None)
def offline_connect(self):
    raise RuntimeError('历史工作台禁止建立OpenD连接')
provider_module.Provider.connect=offline_connect
workspace_module.now_et=lambda:FIXED
st.session_state['_history_archive_path']=str(snapshots().archive.path)
st.session_state['_legacy_history']=snapshots().raw
st.session_state['_daily_update_root']=str(UPDATE_ROOT)
st.session_state['_history_runtime_config']=HISTORY_CONFIG
runpy.run_path(str(ROOT/'app.py'),run_name='__main__')
