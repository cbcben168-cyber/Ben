import numpy as np
import pandas as pd
import pytest
from spy_research.outcomes import forward,simulate_path
from spy_research.inference import bootstrap,holm,match

def minute_path():
    time=pd.date_range('2026-10-02 13:30',periods=10,freq='min',tz='UTC')
    return pd.DataFrame(dict(session_date='2026-10-02',ts_start_utc=time,ts_end_utc=time+pd.Timedelta(minutes=1),
                            open=np.arange(10)+100.,high=np.arange(10)+102.,low=np.arange(10)+99.,close=np.arange(10)+101.))

def test_forward_entry_horizon_cost_and_short_sign():
    path=minute_path()
    events=pd.DataFrame([dict(event_id='e',bar_id=0,session_date='2026-10-02',setup='TEST',direction=1,signal_time=path.ts_start_utc.iloc[5])])
    out=forward(path,events,[5,15])
    assert out.iloc[0].entry_price==105 and out.iloc[0].exit_price==110
    assert out.iloc[0].net_bps==pytest.approx((110/105-1)*10000-2)
    assert out.iloc[1].status=='CENSORED'
    events['direction']=-1
    assert forward(path,events,[5]).iloc[0].gross_bps==-out.iloc[0].gross_bps

def test_conservative_ambiguous_stop_and_gap():
    path=pd.DataFrame([dict(open=100.,high=102.,low=98.,close=101.)])
    result=simulate_path(path,1,atr=1,sl_atr=1,tp_r=1)
    assert result['reason']=='STOP' and result['exit_price']==99
    path=pd.DataFrame([dict(open=100.,high=100.5,low=99.5,close=100.),dict(open=98.,high=98.5,low=97.,close=98.)])
    assert simulate_path(path,1,1,sl_atr=1,tp_r=1)['exit_price']==98

def test_holm_uses_whole_registered_family():
    assert holm([.001,.01])==pytest.approx([.012,.11])

def test_bootstrap_preserves_shared_control_date():
    dates=[str(i) for i in range(30)]
    events=pd.DataFrame(dict(event_id=['a','b'],session_date=['10','11'],net_bps=[3.,3.]))
    links=pd.DataFrame(dict(event_id=['a','b'],control_id=[0,0],control_date=['0','0'],weight=[1.,1.]))
    result=bootstrap(events,links,{0:1.},dates,reps=1000)
    assert result['delta_mean']==2.
    # A shared control absent from a date draw cannot remain in that replicate.
    assert result['valid_reps']<950 and result['delta_ci']==[None,None]

def test_known_positive_and_zero_edge_fixtures():
    dates=[str(i) for i in range(30)]
    events=pd.DataFrame(dict(event_id=[str(i) for i in range(10,30)],session_date=[str(i) for i in range(10,30)],net_bps=[3.]*20))
    rows=[dict(event_id=str(i),control_id=j,control_date=str(j),weight=.2) for i in range(10,30) for j in range(5)]
    result=bootstrap(events,pd.DataFrame(rows),{i:0. for i in range(5)},dates,reps=1000)
    assert result['net_ci'][0]>0 and result['delta_ci'][0]>0
    events['net_bps']=0.
    result=bootstrap(events,pd.DataFrame(rows),{i:0. for i in range(5)},dates,reps=1000)
    assert result['p_net']==1 and result['p_delta']==1

def test_matching_never_crosses_split_or_same_day():
    bars=pd.DataFrame(dict(session_date=['a','a','b','c'],split=['train','train','train','locked_oos'],bucket=['10:00']*4,
        gap_state=['Flat']*4,volatility_state=['Normal']*4,gap_ratio=[0.]*4,volatility=[.01]*4,trigger_ORB5_1=[True,False,False,False]))
    events=pd.DataFrame([dict(event_id='event',bar_id=0,session_date='a',setup='ORB5',direction=1)])
    links=match(bars,events,{'gap_ratio':1.,'volatility':1.},'train')
    assert links.control_id.tolist()==[2]
