import numpy as np
import pandas as pd
import pytest
from spy_research.gamma import clean_chain,exposure,roots,levels,candidates

NOW=pd.Timestamp('2026-10-05 14:00:00Z')

def chain():
    return pd.DataFrame([dict(code=f'US.SPY{i}',option_type=kind,option_strike_price=strike,
        option_open_interest=oi,option_implied_volatility=20,option_contract_size=100,
        option_gamma=.01,strike_time='2026-10-09',update_time='2026-10-05 10:00:00')
        for i,(kind,strike,oi) in enumerate([('CALL',780,1000),('PUT',760,1000)])])

def test_iv_units_exposure_sign_and_scaling():
    f=clean_chain(chain(),NOW)
    assert f.iv.tolist()==[.2,.2]
    assert exposure(f.iloc[[0]],[770])[0]>0
    assert exposure(f.iloc[[1]],[770])[0]<0
    doubled=f.copy();doubled['oi']*=2
    assert exposure(doubled,[770])[0]==pytest.approx(exposure(f,[770])[0]*2)
    s=770.;row=f.iloc[0];d=(np.log(s/row.strike)+.5*row.iv**2*row.years)/(row.iv*np.sqrt(row.years))
    expected=np.exp(-d*d/2)/np.sqrt(2*np.pi)/(s*row.iv*np.sqrt(row.years))*row.oi*100*s*s*.01
    assert exposure(f.iloc[[0]],[s])[0]==pytest.approx(expected)

def test_no_root_multiple_root_and_zero_profile():
    assert roots([1,2,3],[1,2,3])==[]
    assert roots([1,2,3],[-1,1,-1])==[1.5,2.5]
    assert roots([1,2,3],[0,0,0])==[]

def test_levels_and_freshness_fail_closed():
    raw=chain();r,curve=levels(raw,770,NOW,NOW,raw.code)
    assert r[0]['status']=='UNAVAILABLE'
    assert r[1]['status']=='DIAGNOSTIC_ONLY'
    assert r[1]['call_wall']==780 and r[1]['put_wall']==760
    assert r[1]['gamma_zero'] is not None
    assert not r[1]['formal_data_gate'] and len(curve)==401
    stale,_=levels(raw,770,NOW+pd.Timedelta(minutes=3),NOW,raw.code)
    assert stale[1]['status']=='STALE'
    missing,_=levels(raw.iloc[:1],770,NOW,NOW,raw.code)
    assert missing[1]['status']=='UNAVAILABLE'
    extra,_=levels(raw,770,NOW,NOW,list(raw.code)+['missing'])
    assert extra[1]['status']=='INCOMPLETE'

@pytest.mark.parametrize('field,value',[('option_implied_volatility',0),('option_open_interest',-1),('option_contract_size',50),('option_gamma',np.inf),('strike_time','2026-10-02')])
def test_bad_contracts_not_qualified(field,value):
    raw=chain();raw.loc[0,field]=value
    assert not clean_chain(raw,NOW).valid.all()

def test_duplicate_contract_rejected():
    raw=chain();raw.loc[1,'code']=raw.loc[0,'code']
    with pytest.raises(ValueError,match='DUPLICATE'):clean_chain(raw,NOW)

def bars():
    starts=pd.date_range('2026-10-05 14:00Z',periods=4,freq='5min')
    return pd.DataFrame(dict(ts_start_utc=starts,ts_end_utc=starts+pd.Timedelta(minutes=5),
        open=[99,99,101,102],high=[100,102,103,104],low=[98,98,99,101],close=[99,101,102,103]))

def test_retest_prefix_gap_freeze_and_next_actual_time():
    level=dict(status='DIAGNOSTIC_ONLY',scope='7D',call_wall=100,put_wall=90,gamma_zero=100,net_gex=-1)
    b=bars(); available=b.ts_start_utc.iloc[0];now=b.ts_end_utc.iloc[2]+pd.Timedelta(seconds=12)
    result=candidates(b,level,available,now)
    assert set(result.setup)=={'CALL_WALL_BREAK_RETEST','GAMMA_ZERO_RECLAIM'}
    assert (pd.to_datetime(result.entry_not_before,utc=True)>now).all()
    assert candidates(b.iloc[:2],level,available,b.ts_end_utc.iloc[1]).empty
    assert candidates(b,dict(level,status='STALE'),available,now).empty
    assert candidates(b,level,b.ts_start_utc.iloc[2],now).empty
    assert candidates(b.drop(index=1),level,available,now).empty
    later=candidates(b,level,available,b.ts_end_utc.iloc[-1])
    assert result[['setup','signal_time']].equals(later[['setup','signal_time']])

def test_bounce_requires_positive_model_and_right_side_target():
    b=bars().iloc[:2].copy();b.loc[0,'close']=101;b.loc[1,'low']=99;b.loc[1,'close']=102
    level=dict(status='DIAGNOSTIC_ONLY',scope='7D',call_wall=101,put_wall=100,gamma_zero=None,net_gex=1)
    r=candidates(b,level,b.ts_start_utc.iloc[0],b.ts_end_utc.iloc[-1])
    assert r.iloc[0].setup=='PUT_WALL_BOUNCE' and r.iloc[0].target_reference is None
    assert candidates(b,dict(level,net_gex=-1),b.ts_start_utc.iloc[0],b.ts_end_utc.iloc[-1]).empty

def test_short_retest_and_exact_minute_detection():
    b=bars().copy()
    for col in ['open','high','low','close']:
        b[col]=200-b[col]
    b[['high','low']]=b[['low','high']].to_numpy()
    level=dict(status='DIAGNOSTIC_ONLY',scope='7D',call_wall=110,put_wall=100,gamma_zero=100,net_gex=-1)
    now=b.ts_end_utc.iloc[2]
    r=candidates(b,level,b.ts_start_utc.iloc[0],now)
    assert set(r.setup)=={'PUT_WALL_BREAK_RETEST','GAMMA_ZERO_LOSS'}
    assert (pd.to_datetime(r.entry_not_before,utc=True)==now+pd.Timedelta(minutes=1)).all()
