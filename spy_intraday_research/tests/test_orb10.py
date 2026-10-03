import numpy as np
import pandas as pd
import pytest
from spy_research.orb10 import trade_day,backtest,clustered_ci,equity,study
from spy_research.data import schedule,aggregate5_fast


def session(date='2026-10-02',direction=1):
    day=schedule(date,date).iloc[0]
    ts=pd.date_range(day.open,day.close-pd.Timedelta(minutes=1),freq='min')
    minute=pd.DataFrame(dict(code='US.SPY',session_date=date,ts_start_utc=ts,
        ts_end_utc=ts+pd.Timedelta(minutes=1),open=100.,high=100.5,low=99.5,close=100.,volume=10.))
    # OR=[99,101]. First close breakout occurs at 09:45, next 5m entry 102.
    minute.loc[:9,'high']=101;minute.loc[:9,'low']=99
    minute.loc[14,['high','close']]=[102,102]
    minute.loc[15:,['open','high','low','close']]=[102,102.5,101.5,102]
    if direction==-1:
        for col in ['open','high','low','close']:minute[col]=200-minute[col]
        minute[['high','low']]=minute[['low','high']].to_numpy()
    return minute,aggregate5_fast(minute),day


@pytest.mark.parametrize('direction',[1,-1])
def test_actual_next_5m_entry_stop_and_3r(direction):
    minute,five,day=session(direction=direction)
    if direction==1:minute.loc[20,'high']=107
    else:minute.loc[20,'low']=93
    result=backtest(minute,aggregate5_fast(minute),schedule('2026-10-02','2026-10-02')).iloc[0]
    assert result.status=='COMPLETE' and result.reason=='TARGET'
    assert result.entry_price==(102 if direction==1 else 98)
    assert result.stop==(100.5 if direction==1 else 99.5)
    assert result.target==(106.5 if direction==1 else 93.5)
    assert result.gross_r==pytest.approx(3) and result.net_r<3
    assert pd.Timestamp(result.entry_time)==day.open+pd.Timedelta(minutes=15)


def test_same_minute_stop_wins_and_gap_actual_open():
    minute,five,day=session();minute.loc[20,['high','low']]=[107,100]
    r=trade_day(minute,aggregate5_fast(minute),day)
    assert r['reason_override']=='STOP' and r['both_hit'] and r['gross_r']==pytest.approx(-1)
    minute,five,day=session();minute.loc[20,['open','high','low','close']]=[99,100,98,99]
    r=trade_day(minute,aggregate5_fast(minute),day)
    assert r['reason_override']=='GAP_STOP' and r['exit_price']==99 and r['gross_r']<-1


def test_gap_target_conservative_and_skip_no_second_trade():
    minute,five,day=session();minute.loc[20,['open','high','low','close']]=[108,109,107,108]
    r=trade_day(minute,aggregate5_fast(minute),day)
    assert r['reason_override']=='GAP_TARGET' and r['exit_price']==106.5
    minute,five,day=session();minute.loc[15,['open','low']]=[100,99]
    r=backtest(minute,aggregate5_fast(minute),schedule('2026-10-02','2026-10-02')).iloc[0]
    assert r.status=='SKIPPED' and r.reason=='ENTRY_BEYOND_STOP'
    assert r.signal_time== (day.open+pd.Timedelta(minutes=15)).isoformat()


@pytest.mark.parametrize('close_minute,allowed',[(55,True),(60,False)])
def test_strict_1030_cutoff(close_minute,allowed):
    minute,five,day=session()
    minute.loc[10:,['open','high','low','close']]=[100,100.5,99.5,100]
    minute.loc[close_minute-1,['high','close']]=[102,102]
    minute.loc[close_minute:,['open','high','low','close']]=[102,102.5,101.5,102]
    r=backtest(minute,aggregate5_fast(minute),schedule('2026-10-02','2026-10-02')).iloc[0]
    assert (r.status=='COMPLETE')==allowed


def test_touch_is_not_breakout_and_first_direction_only():
    minute,five,day=session();minute.loc[14,['high','close']]=[101,101]
    minute.loc[15:,['open','high','low','close']]=[100,100.5,99.5,100]
    assert trade_day(minute,aggregate5_fast(minute),day)['status']=='NO_TRADE'
    minute,five,day=session();minute.loc[24:,['open','high','low','close']]=[98,98.5,97.5,98]
    r=backtest(minute,aggregate5_fast(minute),schedule('2026-10-02','2026-10-02'))
    assert len(r)==1 and r.iloc[0].direction==1


def test_full_session_missing_and_half_day_close():
    minute,five,day=session()
    assert trade_day(minute.drop(index=30),five,day)['quality']=='FAILED_SESSION'
    minute,five,day=session(date='2026-11-27')
    r=trade_day(minute,five,day)
    assert r['reason_override']=='RTH_CLOSE' and pd.Timestamp(r['exit_time'])==day.close
    assert len(minute)==210


def test_zero_range_skip_and_frequency_mismatch():
    minute,five,day=session();minute.loc[:9,['open','high','low','close']]=100
    assert trade_day(minute,aggregate5_fast(minute),day)['reason_override']=='ZERO_RANGE'
    minute,five,day=session();five.loc[3,'open']=103
    with pytest.raises(ValueError,match='ENTRY_FREQUENCY'):trade_day(minute,five,day)


def test_pnl_equity_and_date_resampling():
    daily=pd.DataFrame(dict(status=['COMPLETE','NO_TRADE','COMPLETE'],net_bps=[100,0,-200]))
    nav,dd=equity(daily)
    assert nav[-1]==pytest.approx(1.01*.98) and dd.min()==pytest.approx(-.02)
    assert clustered_ci(daily,reps=1000)==clustered_ci(daily,reps=1000)
    assert clustered_ci(pd.DataFrame({'status':['NO_TRADE']}))==[None,None]


def test_registered_run_cannot_overwrite(tmp_path):
    (tmp_path/'artifacts/orb10_3r_v1/train').mkdir(parents=True)
    with pytest.raises(ValueError,match='ALREADY_REGISTERED'):study(tmp_path)
