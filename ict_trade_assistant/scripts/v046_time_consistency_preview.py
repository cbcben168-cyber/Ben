"""Isolated presentation fixture. Nov 9 daily data below is synthetic, not fetched.

Only reads accepted local archives; never opens user databases or OpenD.
"""
import copy
import os
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pandas as pd
import streamlit as st
from desk.clock import ET
from desk.decision_home import render_home
from desk.futu_daily import FutuDailyArchive
from desk.futu_hourly import FutuHourlyArchive

st.set_page_config(page_title='v0.4.6 时间一致性隔离验收',layout='wide')


@st.cache_data(show_spinner=False)
def snapshots(daily_path,hourly_path):
    import json
    codes=list(json.loads((Path(hourly_path)/'manifest.json').read_text(encoding='utf-8'))['symbols'])
    data={}
    for code in codes:
        dm,day=FutuDailyArchive(daily_path).read(code)
        hm,hour=FutuHourlyArchive(hourly_path).read(code)
        data[code]=dict(daily=day,minute=pd.DataFrame(),futu_daily=day,futu_coverage=dm,
            futu_hourly=hour,hourly_coverage=hm,health=dict(source='LOCAL_ARCHIVE',quality='UNAVAILABLE'),
            _price_basis_unverified=True)
    return data


base=snapshots(os.environ['ICT_FUTU_DAILY_ARCHIVE'],os.environ['ICT_FUTU_HOURLY_ARCHIVE'])
case=st.radio('隔离情景',['真实归档基线','日K合成更新至11月9日'],horizontal=True)
data=copy.deepcopy(base)
if case=='日K合成更新至11月9日':
    st.warning('隔离测试：11月9日日K为受控合成资料，非真实行情更新；1H仍读取原验收档案，未更新或改写。')
    wall=pd.Timestamp('2026-11-09T16:02:00',tz=ET).to_pydatetime()
    for item in data.values():
        day=item['daily'];row=day.iloc[-1].copy()
        row['ts']=pd.Timestamp('2026-11-09',tz=ET).tz_convert('UTC');row['time_key']='2026-11-09 00:00:00'
        for key in ('open','high','low','close'):row[key]+=1
        day=pd.concat([day,pd.DataFrame([row])],ignore_index=True)
        day['source']='ISOLATED_SYNTHETIC_DAY_QFQ'
        item.update(daily=day,futu_daily=day,futu_coverage=dict(item['futu_coverage'],
            contract='ISOLATED_SYNTHETIC_DAY/QFQ',source='ISOLATED_SYNTHETIC_DAY',
            valuation_date='2026-11-10',last='2026-11-09',simulation=True))
else:
    st.info('真实归档基线：日K与1H均读取原验收资料；仅历史展示，实时资格关闭。')
    wall=pd.Timestamp('2026-11-09T03:00:00',tz=ET).to_pydatetime()

st.selectbox('独立窗口观察标的',list(data),key='tc_symbol')
def pick(code,key):
    st.session_state['tc_symbol']=code
render_home(st.session_state['tc_symbol'],data,None,None,[],[],wall,wall,pick,enabled=list(data))
