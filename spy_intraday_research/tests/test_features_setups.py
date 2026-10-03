import numpy as np
import pandas as pd
from spy_research.data import schedule,aggregate5_fast
from spy_research.features import build,fit_states,apply_states
from spy_research.setups import detect

def minutes(dates):
    chunks=[]
    for i,date in enumerate(dates):
        s=schedule(date,date).iloc[0]
        time=pd.date_range(s.open,s.close,freq='min',inclusive='left')
        value=100+i*.15+np.arange(len(time))*.001
        chunks.append(pd.DataFrame(dict(code='US.SPY',session_date=date,ts_start_utc=time,
            ts_end_utc=time+pd.Timedelta(minutes=1),open=value,high=value+.01,low=value-.01,close=value+.002,volume=10.,turnover=1000.)))
    return pd.concat(chunks,ignore_index=True)

def bars(closes,date='2026-10-02'):
    s=schedule(date,date).iloc[0]
    times=pd.date_range(s.open+pd.Timedelta(minutes=5),periods=len(closes),freq='5min')
    frame=pd.DataFrame(dict(ts_end_utc=times,session_date=date,open=np.array(closes)-.01,
        high=np.array(closes)+.02,low=np.array(closes)-.02,close=closes,atr_prev=1.,prev_close=100.,
        prev_high=101.,prev_low=99.,vwap=100.,vwap_slope=.02,or15_high=101.,or15_low=99.,
        gap_ratio=0.,gap_state='Flat',volatility_state='Normal',corporate_action=False))
    local=times.tz_convert('America/New_York')
    frame['minute_of_day']=local.hour*60+local.minute
    return frame

def test_causal_features_and_train_thresholds():
    dates=[d.strftime('%Y-%m-%d') for d in schedule('2026-08-03','2026-09-18').index]
    original=minutes(dates[:-1]); later=minutes(dates[-1:]); later[['open','high','low','close']]+=900
    left=build(original,aggregate5_fast(original),set())
    right=build(pd.concat([original,later]),aggregate5_fast(pd.concat([original,later])),set())
    cols=['atr_prev','prev_close','prev_high','prev_low','volatility','gap_ratio','vwap','or_ratio','volume_expansion']
    pd.testing.assert_frame_equal(left[cols],right.iloc[:len(left)][cols])
    model=fit_states(left,dates[20:25]); labels=apply_states(left,model)
    assert (labels.available_at_utc==labels.ts_end_utc).all()
    assert labels.loc[labels.minute_of_day<585,'or_state'].eq('UNKNOWN').all()
    assert left.groupby('session_date').vwap.first().iloc[-1]<200

def test_orb_next_bar_and_once_per_direction():
    frame=bars([100.,100.2,100.3,100.,100.4,100.5])
    _,events=detect(frame)
    chosen=events[(events.setup=='ORB5')&(events.direction==1)]
    assert len(chosen)==1
    assert chosen.signal_time.iloc[0]==frame.ts_end_utc.iloc[1]

def test_future_prefix_does_not_change_events():
    frame=bars([100.,100.2,100.3,100.,100.4,100.5])
    _,early=detect(frame.iloc[:3]); _,full=detect(frame)
    assert set(early.event_id)<=set(full.event_id)

def test_failed_breakout_requires_later_reclaim():
    frame=bars([100.,101.5,100.5,100.4])
    _,events=detect(frame)
    chosen=events[(events.setup=='FAILED_BREAKOUT')&(events.direction==-1)]
    assert len(chosen)==1 and chosen.signal_time.iloc[0]==frame.ts_end_utc.iloc[2]

def test_vwap_pullback_and_gap_fade():
    frame=bars([100.4]*6)
    frame.loc[5,['open','low','close']]=[100.1,100.,100.3]
    _,events=detect(frame)
    assert ((events.setup=='VWAP_PULLBACK')&(events.direction==1)).any()
    gap=bars([101.2,101.3,101.4,100.8])
    gap['gap_ratio']=1.; gap['vwap']=101.2; gap['or15_low']=101.1
    _,events=detect(gap)
    assert ((events.setup=='GAP_FADE')&(events.direction==-1)).any()
    gap['corporate_action']=True
    _,events=detect(gap)
    assert not (events.setup=='GAP_FADE').any()
