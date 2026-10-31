from datetime import date, datetime
import json
import pandas as pd
import pytest
from desk.clock import ET
from desk.analytics import normalize, previous_week_levels
from desk.plans import risk_reward, evaluate_plan
from desk.store import Store


def daily(days):
    raw=pd.DataFrame(dict(time_key=[d+' 00:00:00' for d in days],open=100.,high=110.,low=90.,close=105.,volume=1.))
    return normalize(raw,'DAY',datetime(2026,12,1,tzinfo=ET))


def test_previous_week_complete_missing_and_current_excluded():
    f=daily(['2026-10-19','2026-10-20','2026-10-21','2026-10-22','2026-10-23','2026-10-26'])
    f.loc[5,'high']=999
    now=datetime(2026,10,29,10,tzinfo=ET)
    result=previous_week_levels(f,now.date(),now)
    assert result['high']==110 and result['low']==90 and result['expected']==5
    assert previous_week_levels(f.drop(index=2),now.date(),now)['high'] is None
    assert previous_week_levels(pd.concat([f,f.iloc[:1]]),now.date(),now)['high'] is None


def test_holiday_early_close_week():
    f=daily(['2026-11-23','2026-11-24','2026-11-25','2026-11-27'])
    now=datetime(2026,11,30,10,tzinfo=ET)
    result=previous_week_levels(f,now.date(),now)
    assert result['expected']==4 and result['high']==110
    f.loc[3,'eligible']=False
    assert previous_week_levels(f,now.date(),now)['high'] is None


def payload():
    return dict(symbol='US.SPY',strategy_version='ICT-人工计划-v1',direction='LONG',low=100.,high=101.,invalid=99.,target_low=105.,target_high=106.,memo='原计划')


def test_versions_cancellation_restart_conflict_and_alerts(tmp_path):
    s=Store(tmp_path/'p.db'); p=payload(); ident,v=s.save_plan(p)
    first=s.plans()[0]; assert v==1 and risk_reward(first)==2
    evaluate_plan(s,first,dict(price=100.,quality='STALE'),'2026-10-29',10)
    assert len(s.table('events'))==1
    evaluate_plan(s,first,dict(price=100.,quality='AVAILABLE'),'2026-10-29',10)
    evaluate_plan(s,first,dict(price=100.,quality='AVAILABLE'),'2026-10-29',10)
    alerts=s.table('events'); assert len(alerts)==2
    event=json.loads(alerts.iloc[0].payload)
    assert event['plan_id']==ident and event['plan_version']==1
    p['memo']='修订';s.save_plan(p,ident,1)
    with pytest.raises(ValueError):s.save_plan(p,ident,1)
    s.save_plan(p,ident,2,cancel=True)
    reopened=Store(tmp_path/'p.db');hist=reopened.plan_history(ident)
    assert [r['version'] for r in hist]==[1,2,3]
    assert hist[0]['memo']=='原计划' and hist[1]['memo']=='修订'
    assert hist[0]['created_at']==hist[-1]['created_at']
    assert risk_reward(reopened.plans()[0]) is None
    count=len(s.table('events'))
    evaluate_plan(s,reopened.plans()[0],dict(price=100.,quality='AVAILABLE'),'2026-10-29',10)
    evaluate_plan(s,first,dict(price=100.,quality='AVAILABLE'),'2026-10-30',10)
    assert len(s.table('events'))==count


def test_invalid_prices_short_and_missing_rr(tmp_path):
    s=Store(tmp_path/'p.db');p=payload();p['invalid']=102
    with pytest.raises(ValueError):s.save_plan(p)
    assert risk_reward({'status':'ACTIVE'}) is None
    p.update(direction='SHORT',invalid=102,target_low=95,target_high=96)
    ident,v=s.save_plan(p)
    assert risk_reward(s.plans()[0])==2


def test_sqlite_connections_release_file(tmp_path):
    p=tmp_path/'release.db';s=Store(p)
    s.note('US.SPY','保存')
    s.plans();s.table('events');s.acknowledged()
    p.unlink()
    assert not p.exists()


def test_candidate_selection_survives_period_change(tmp_path,market_fixture):
    from unittest.mock import patch
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    from pathlib import Path
    st.cache_data.clear()
    store=Store(tmp_path/'ui.db');z=payload();store.save('zones',{'US.QQQ':z})
    from datetime import datetime
    with patch('desk.store.Store',return_value=store),patch('desk.provider.Provider.fetch',return_value=market_fixture),patch('desk.workspace.now_et',return_value=datetime(2026,10,30,10,10,tzinfo=ET)):
        app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'app.py'),default_timeout=30).run()
        app.button(key='pick_US.QQQ_MANUAL').click().run()
        assert not app.exception and app.session_state['desk_symbol']=='US.QQQ'
        period=next(r for r in app.radio if r.label=='周期')
        period.set_value('4H').run()
        assert not app.exception and app.session_state['desk_symbol']=='US.QQQ'


def test_pdh_pdl_previous_session_dst_and_extended_isolation():
    from desk.analytics import key_levels
    now=datetime(2026,11,2,10,tzinfo=ET)
    ts=pd.date_range('2026-10-30 09:30',periods=390,freq='min')
    raw=pd.DataFrame(dict(time_key=ts.astype(str),open=100.,high=102.,low=99.,close=101.,volume=1.))
    extra=pd.DataFrame([dict(time_key='2026-10-30 09:29:00',open=100.,high=999.,low=1.,close=100.,volume=1.)])
    f=normalize(pd.concat([extra,raw],ignore_index=True),'1M',now)
    result=key_levels(f,now.date(),now)['PREVIOUS_RTH']
    assert result['high']==102 and result['low']==99 and result['rows']==390
    assert '2026-10-30 09:30:00-04:00'==result['start']
    assert now.utcoffset().total_seconds()==-5*3600
    assert key_levels(f.drop(index=100),now.date(),now)['PREVIOUS_RTH']['high'] is None
