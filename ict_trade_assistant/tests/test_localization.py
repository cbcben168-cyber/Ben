from pathlib import Path
from unittest.mock import patch
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from desk.i18n import zh, details, table
from desk.store import Store

@pytest.mark.parametrize('status,expected', [
    ('STALE','行情数据已过期'), ('UNAVAILABLE','行情数据不可用'),
    ('INCONSISTENT','行情数据不一致')])
def test_chinese_blocked_home(tmp_path, status, expected):
    import streamlit as st
    st.cache_data.clear()
    store = Store(tmp_path/'test.sqlite3')
    fixture = dict(health=dict(quality=status, reason='行情检查未通过',
        source='FUTU_OPEND', received_at='2026-10-29T00:00:00Z'),
        minute=pd.DataFrame(), daily=pd.DataFrame(), errors=[])
    with patch('desk.store.Store',return_value=store), patch('desk.provider.Provider.fetch',return_value=fixture):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py')).run()
        assert not app.exception
        assert any(expected in x.value for x in app.caption)
        assert any('已阻止新入场审查' in x.value for x in app.error)
        assert any('暂停新增操作' in x.value for x in app.warning)
        assert any('未连接交易记录' in x.value for x in app.info)
        assert not any('CANCEL SETUP' in x.value or 'NO NEW ACTION' in x.value for x in app.warning)

def test_display_only_mapping():
    original={'quality':'STALE','direction':'LONG','stage':'等待 MSS'}
    result=details(original)
    assert result['数据状态']=='行情数据已过期'
    assert result['方向']=='潜在做多'
    assert result['阶段']=='等待 市场结构转变'
    assert original['quality']=='STALE'
    frame=pd.DataFrame([dict(kind='ALERT', reason='用户原文 WAIT', symbol='US.SPY')])
    translated=table(frame)
    assert translated.iloc[0]['事件类型']=='价格提醒'
    assert translated.iloc[0]['原因']=='用户原文 WAIT'
    assert zh('INVALIDATED')=='当前交易计划已失效'
