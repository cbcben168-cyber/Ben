import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from es_mes.core import calendar,validate,run,hold_reference,one_day
from es_mes.cli import main,request,selection,import_data,backtest


def data(product='ES',date='2026-10-02'):
    cal=calendar(date,date);day=cal.iloc[0];code='US.'+product+'2612'
    ts=pd.date_range(day.open,day.close-pd.Timedelta(minutes=1),freq='min')
    raw=pd.DataFrame(dict(ts_start_utc=ts,contract=code,open=100.,high=100.5,low=99.5,close=100.,volume=10.))
    raw.loc[:9,'high']=101;raw.loc[:9,'low']=99
    raw.loc[14,['high','close']]=[102,102]
    raw.loc[15:,['open','high','low','close']]=[102,102.5,101.5,102]
    roll=pd.DataFrame([dict(session_date=date,contract=code,expires_on='2026-12-18',known_at_utc='2026-09-30T12:00:00Z')])
    return raw,roll,cal


def test_default_disabled_and_choice_switches(tmp_path,capsys):
    assert selection(tmp_path)==[]
    assert main(['status','--root',str(tmp_path)])==0
    assert not (tmp_path/'state').exists()
    assert main(['backtest','--product','ES','--root',str(tmp_path)])==1
    assert 'RESEARCH_DISABLED' in capsys.readouterr().out
    for choice,expected in [('ES',['ES']),('MES',['MES']),('both',['ES','MES']),('none',[])]:
        assert main(['select','--choice',choice,'--root',str(tmp_path)])==0
        assert selection(tmp_path)==expected


@pytest.mark.parametrize('product,point',[('ES',50),('MES',5)])
def test_actual_multiplier_costs_and_target(product,point):
    raw,roll,cal=data(product);raw.loc[20,'high']=108
    minute,cal=validate(raw,roll,product,'2026-10-02','2026-10-02')
    result=run(minute,cal,product,2.,1).iloc[0]
    assert result.status=='COMPLETE' and result.reason=='TARGET'
    assert result.entry_price==102.25 and result.target==107.5
    assert result.net_usd==pytest.approx(5.25*point-2)
    assert result.net_r<3


def test_tick_rounding_and_stop_first_gap():
    raw,roll,cal=data();raw.loc[:9,'low']=99.75 # width1.25 -> stop100.6875 rounds outward100.5
    raw.loc[20,['high','low']]=[108,100]
    minute,cal=validate(raw,roll,'ES','2026-10-02','2026-10-02')
    r=run(minute,cal,'ES',2.,1).iloc[0]
    assert r.stop==100.5 and r.exit_price==100.25 and r.both_hit
    raw,roll,cal=data();raw.loc[20,['open','high','low','close']]=[99,100,98,99]
    minute,cal=validate(raw,roll,'ES','2026-10-02','2026-10-02')
    r=run(minute,cal,'ES',2.,1).iloc[0]
    assert r.reason=='GAP_STOP' and r.exit_price==98.75


def test_exact_limit_touch_not_assumed_fill():
    raw,roll,cal=data();raw.loc[20,'high']=106.5
    minute,cal=validate(raw,roll,'ES','2026-10-02','2026-10-02')
    assert run(minute,cal,'ES',0.,0).iloc[0].reason=='RTH_CLOSE'


@pytest.mark.parametrize('bad',['missing','duplicate','naive','tick','alias','expiry','late_roll'])
def test_quality_fail_closed(bad):
    raw,roll,cal=data()
    if bad=='missing':raw=raw.drop(index=30)
    elif bad=='duplicate':raw=pd.concat([raw,raw.iloc[[30]]])
    elif bad=='naive':raw['ts_start_utc']=raw.ts_start_utc.dt.tz_localize(None)
    elif bad=='tick':raw.loc[20,'close']=102.1
    elif bad=='alias':raw['contract']='US.ESmain'
    elif bad=='expiry':roll['expires_on']='2026-10-02'
    else:roll['known_at_utc']='2026-10-02T14:00:00Z'
    with pytest.raises(ValueError):validate(raw,roll,'ES','2026-10-02','2026-10-02')


def test_dst_half_day_and_no_overnight_splice():
    raw,roll,cal=data(date='2026-11-27')
    minute,_=validate(raw,roll,'ES','2026-11-27','2026-11-27')
    assert len(minute)==210 and cal.iloc[0].open.hour==14
    assert run(minute,cal,'ES',0.,0).iloc[0].exit_time==cal.iloc[0].close.isoformat()
    assert hold_reference(minute,'ES',2.,1)['net_usd']==pytest.approx((102-100-.5)*50-2)


def test_roll_cannot_use_same_day_future_volume():
    a,ra,_=data(date='2026-10-01');b,rb,_=data()
    b['contract']='US.ES2703';rb['contract']='US.ES2703';rb['expires_on']='2027-03-19'
    rb['known_at_utc']='2026-10-02T12:00:00Z'
    with pytest.raises(ValueError,match='ROLL_LOOKAHEAD'):
        validate(pd.concat([a,b]),pd.concat([ra,rb]),'ES','2026-10-01','2026-10-02')


def test_import_immutable_and_sample_not_formal(tmp_path):
    raw,roll,cal=data()
    result=import_data(tmp_path,'ES',raw,roll,'2026-10-02','2026-10-02','TEST_SYNTHETIC_UNIT_FIXTURE_ONLY')
    assert not result['formal_split_eligible']
    with pytest.raises(ValueError,match='ALREADY_REGISTERED'):import_data(tmp_path,'ES',raw,roll,'2026-10-02','2026-10-02','fixture')
    with pytest.raises(ValueError,match='500_SESSIONS'):backtest(tmp_path,'ES')


def test_permission_not_retried_and_costs_explicit(tmp_path,capsys):
    from futu import RET_ERROR
    calls=[]
    def denied():calls.append(1);return RET_ERROR,'权限 password-do-not-log'
    with pytest.raises(ValueError,match='^FUTURES_PERMISSION_DENIED$'):request(denied)
    assert len(calls)==1
    assert main(['costs','--product','ES','--root',str(tmp_path)])==1
    assert 'password' not in capsys.readouterr().out
    assert not (tmp_path/'state/costs_ES.json').exists()


def test_short_target_and_first_trade_only():
    raw,roll,cal=data()
    for col in ['open','high','low','close']:raw[col]=200-raw[col]
    raw[['high','low']]=raw[['low','high']].to_numpy()
    raw.loc[20,'low']=92.25
    minute,cal=validate(raw,roll,'ES','2026-10-02','2026-10-02')
    r=run(minute,cal,'ES',2.,1)
    assert len(r)==1 and r.iloc[0].direction==-1 and r.iloc[0].target==92.5
    assert r.iloc[0].net_usd==pytest.approx(5.25*50-2)


@pytest.mark.parametrize('offset,allowed',[(55,True),(60,False)])
def test_strict_1030_cutoff(offset,allowed):
    raw,roll,cal=data()
    raw.loc[10:,['open','high','low','close']]=[100,100.5,99.5,100]
    raw.loc[offset-1,['high','close']]=[102,102]
    raw.loc[offset:,['open','high','low','close']]=[102,102.5,101.5,102]
    minute,cal=validate(raw,roll,'ES','2026-10-02','2026-10-02')
    assert (run(minute,cal,'ES',0.,0).iloc[0].status=='COMPLETE')==allowed


def test_profit_and_daily_drawdown_are_dollars():
    raw,roll,cal=data();raw.loc[20,'low']=100
    minute,cal=validate(raw,roll,'ES','2026-10-02','2026-10-02')
    r=run(minute,cal,'ES',2.,1).iloc[0]
    assert r.net_usd==-102 and r.drawdown_usd==-102 and r.cumulative_usd==-102


def test_manifest_tampering_cannot_open_new_split(tmp_path):
    raw,roll,cal=data()
    import_data(tmp_path,'ES',raw,roll,'2026-10-02','2026-10-02','TEST_SYNTHETIC_UNIT_FIXTURE_ONLY')
    path=tmp_path/'data/ES/manifest.json';meta=json.loads(path.read_text())
    meta['formal_split_eligible']=True;path.write_text(json.dumps(meta))
    with pytest.raises(ValueError,match='REGISTERED_MANIFEST_CHANGED'):backtest(tmp_path,'ES')
