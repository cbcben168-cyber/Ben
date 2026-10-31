"""合成数据仅验证识别及因果顺序，不计算收益。"""
from datetime import datetime, timedelta
import pandas as pd
import pytest
from desk.clock import ET, bounds
from desk.ict_v03 import scan, live_alert_allowed, VERSION


def history():
    rows = []
    for day in ['2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29']:
        start, end = bounds(pd.Timestamp(day).date())
        # 事前严格 swing high=106（第2小时），右2根在14:30收盘。
        hours = [(100,102,99,101),(101,103,99,102),(102,106,100,103),
                 (103,104,99,101),(101,103,99,102),(102,104,99,101),(101,103,99,102)]
        if day == '2026-10-29':
            hours = [(100,102,98,100),(100,108,100,107),(108,110,105,109),
                     (109,110,106,108),(108,109,103,106),(106,108,100,101),(101,102,97,99)]
        for i, ts in enumerate(pd.date_range(start,end,freq='min',inclusive='left')):
            o,h,l,c=hours[i//60]
            rows.append(dict(ts=ts,open=o,high=h,low=l,close=c,volume=1.,session='RTH',eligible=True,source='SYNTHETIC_TEST_ONLY'))
    return pd.DataFrame(rows)


def at(hour, minute=2):
    return datetime(2026,10,29,hour,minute,tzinfo=ET)


def test_confirmed_chain_and_exact_prices():
    r=scan('US.SPY',history(),at(16,2))
    sweep=next(e for e in r['events'] if e['kind']=='SWEEP' and e['direction']=='LONG' and e['occurred_at'].startswith('2026-10-29'))
    assert sweep['level']==99 and sweep['extreme']==98
    assert sweep['atr14']==pytest.approx(31/7)
    assert sweep['invalidation_price']==pytest.approx(98-.1*31/7)
    assert sweep['confirmed_at']==at(10,32).isoformat()
    mss=next(e for e in r['events'] if e['kind']=='MSS' and e['setup_id']==sweep['setup_id'])
    assert mss['structure_price']==106 and mss['confirmed_at']==at(11,32).isoformat()
    assert mss['pivot_known_at']<=sweep['confirmed_at']
    fvg=next(e for e in r['events'] if e['kind']=='FVG' and e['setup_id']==sweep['setup_id'])
    assert (fvg['low'],fvg['high'],fvg['ce'])==(102,105,103.5)
    assert fvg['confirmed_at']==at(12,32).isoformat()
    states=[e['state'] for e in r['events'] if e['setup_id']==sweep['setup_id'] and e['status']=='CONFIRMED']
    assert states==['WATCH','SWEEP','MSS','FVG','CE_REVIEW','INVALIDATED']
    assert len({e['id'] for e in r['events']})==len(r['events'])
    assert all(e['version']==VERSION and e['source'] and e['trigger'] and e['evidence'] for e in r['events'])


@pytest.mark.parametrize('cutoff',[at(10,29),at(10,31),at(11,31),at(12,31),at(13,32)])
def test_prefix_invariance_and_incomplete_bar(cutoff):
    frame=history()
    full=scan('US.SPY',frame,cutoff)
    prefix=scan('US.SPY',frame[frame.ts<cutoff],cutoff)
    assert full==prefix
    assert all(e['confirmed_at'] is None or pd.Timestamp(e['confirmed_at'])<=cutoff for e in full['events'])
    assert not any(e['kind']=='FVG' and e['occurred_at'].startswith('2026-10-29') and e['status']=='CONFIRMED' for e in full['events']) if cutoff<at(12,32) else True


def test_forming_sweep_never_confirmed_early():
    r=scan('US.SPY',history(),at(10,29))
    today=[e for e in r['events'] if e['occurred_at'].startswith('2026-10-29')]
    assert any(e['kind']=='SWEEP' and e['status']=='FORMING' and e['confirmed_at'] is None for e in today)
    assert not any(e['kind']=='MSS' for e in today)


def test_missing_minute_closes_active_chain_and_no_gap_fvg():
    frame=history();frame=frame[frame.ts!=at(11,0)]
    r=scan('US.SPY',frame,at(16,2))
    today=[e for e in r['events'] if e['occurred_at'].startswith('2026-10-29')]
    assert any(e['kind']=='INVALIDATED' and '缺失' in e['reason'] for e in today)
    assert not any(e['kind']=='MSS' for e in today)


def test_missing_previous_day_and_duplicate_fail_closed():
    f=history()
    r=scan('US.SPY',f[f.ts.dt.date!=pd.Timestamp('2026-10-28').date()],at(16,2))
    assert not any(e['kind']=='SWEEP' and e['status']=='CONFIRMED' and e['occurred_at'].startswith('2026-10-29') for e in r['events'])
    assert scan('US.SPY',pd.concat([f,f.iloc[:1]]),at(16,2))['status']=='UNKNOWN'


def test_no_future_pivot_substitution_and_mss_must_close():
    f=history();f.loc[f.ts.dt.date<pd.Timestamp('2026-10-29').date(),'high']=110.
    r=scan('US.SPY',f,at(16,2))
    assert not any(e['kind']=='MSS' for e in r['events'])
    f=history();f.loc[(f.ts>=at(11,0))&(f.ts<at(11,30)),'close']=105.
    # 第二根最高穿越106但收盘未越过，不得在11:32确认。
    r=scan('US.SPY',f,at(11,32))
    assert not any(e['kind']=='MSS' for e in r['events'])


def test_deterministic_repeat_and_versions_and_disabled_live():
    f=history();r=scan('US.SPY',f,at(16,2))
    assert r==scan('US.SPY',f,at(16,2))
    assert not live_alert_allowed(enabled=False,qualified=True)
    assert not live_alert_allowed(enabled=True,qualified=False)
    assert scan('US.SPY',f,at(16,2),timeframe='4H')['status']=='UNKNOWN'
    assert scan('US.SPY',f,datetime(2026,10,29,16,2))['status']=='UNKNOWN'


def test_short_symmetry_and_ambiguous_rejected():
    f=history()
    for col,other in [('open','open'),('close','close')]: f[col]=210-f[col]
    old_high=f.high.copy();f['high']=210-f.low;f['low']=210-old_high
    r=scan('US.QQQ',f,at(16,2))
    assert any(e['kind']=='MSS' and e['direction']=='SHORT' for e in r['events'])
    f=history();mask=(f.ts>=at(9,30))&(f.ts<at(10,30));f.loc[mask,'high']=107
    r=scan('US.SPY',f,at(10,32))
    assert any('双向' in e['reason'] for e in r['events'])
    assert not any(e['kind']=='MSS' for e in r['events'])


def test_independent_fvg_and_forming_occurrence_not_in_future():
    f=history();f.loc[f.ts.dt.date<pd.Timestamp('2026-10-29').date(),'high']=110.
    r=scan('US.SPY',f,at(12,32))
    assert any(z['low']==102 and z['high']==105 for z in r['fvgs'])
    r=scan('US.SPY',history(),at(10,29))
    assert all(pd.Timestamp(e['occurred_at'])<=at(10,29) for e in r['events'])


def test_failed_reclaim_is_explicitly_invalidated():
    f=history();mask=(f.ts>=at(9,30))&(f.ts<at(10,30));f.loc[mask,'close']=98.
    r=scan('US.SPY',f,at(10,32))
    failed=[e for e in r['sweeps'] if e['occurred_at'].startswith('2026-10-29')]
    assert any(e['status']=='INVALIDATED' and '收回' in e['invalidation_reason'] for e in failed)
    assert not any(e['kind']=='MSS' for e in r['events'])


@pytest.mark.parametrize('damage',['nan','bad_price','naive','off_grid','unknown_source'])
def test_corrupt_inputs_fail_closed(damage):
    f=history()
    if damage=='nan':f.loc[0,'high']=float('nan')
    elif damage=='bad_price':f.loc[0,'low']=-1.
    elif damage=='naive':f['ts']=f.ts.dt.tz_localize(None)
    elif damage=='off_grid':f.loc[0,'ts']+=timedelta(seconds=1)
    else:f.loc[0,'source']=''
    assert scan('US.SPY',f,at(16,2))['status']=='UNKNOWN'


def test_price_crossing_in_same_bar_stop_first_and_no_fvg_self_touch():
    r=scan('US.SPY',history(),at(12,32))
    today=[e for e in r['events'] if e['occurred_at'].startswith('2026-10-29')]
    assert any(e['kind']=='FVG' for e in today)
    assert not any(e['kind']=='CE' for e in today)
    f=history();mask=(f.ts>=at(12,30))&(f.ts<at(13,30));f.loc[mask,'low']=97.
    r=scan('US.SPY',f,at(13,32))
    assert not any(e['kind']=='CE' for e in r['events'])
    assert any('优先失效' in e['reason'] for e in r['events'])


def test_linked_fvg_remembers_first_boundary_touch():
    f=history()
    for start,low in [(at(13,30),104.),(at(14,30),106.)]:
        mask=(f.ts>=start)&(f.ts<start+timedelta(hours=1))
        f.loc[mask,['open','high','low','close']]=[108.,110.,low,109.]
    r=scan('US.SPY',f,at(15,32))
    z=next(z for z in r['fvgs'] if z['confirmed_at']==at(12,32).isoformat() and z['direction']=='LONG')
    assert z['status']=='TOUCHED'
    states=[t['state'] for t in z['transitions']]
    assert states==['NEW','WAITING_RETEST','TOUCHED']
    assert all(t['source'] and t['trigger'] and t['version'] and pd.Timestamp(t['confirmed_at'])<=at(15,32) for t in z['transitions'])


def test_confirmed_events_never_change_when_future_bars_arrive():
    f=history()
    f.loc[f.ts==at(10,29),['high','low']]=[109.,97.]
    early=scan('US.SPY',f,at(10,29))
    late=scan('US.SPY',f,at(16,2))
    by_id={e['id']:e for e in late['events']}
    for e in early['events']:
        if e['status']=='CONFIRMED':assert by_id[e['id']]==e
    for e in late['events']:
        if e['status']=='CONFIRMED':
            assert all(pd.Timestamp(b['known_at'])<=pd.Timestamp(e['confirmed_at']) for b in e['evidence'])


def test_dst_transition_preserves_known_at_order():
    f=history()
    target=dict(zip(sorted(set(f.ts.dt.date)),[pd.Timestamp(d).date() for d in ['2026-10-28','2026-10-29','2026-10-30','2026-11-02']]))
    f['ts']=f.ts.map(lambda t:datetime.combine(target[t.date()],t.time(),tzinfo=ET))
    r=scan('US.SPY',f,datetime(2026,11,2,16,2,tzinfo=ET))
    e=next(e for e in r['events'] if e['kind']=='MSS')
    assert e['confirmed_at'].endswith('-05:00') and e['pivot_known_at'].endswith('-04:00')
    sweep=next(s for s in r['events'] if s['id']==e['associated_sweep'])
    assert pd.Timestamp(e['pivot_known_at'])<=pd.Timestamp(sweep['confirmed_at'])


def test_gap_equality_is_not_fvg_and_pivot_ties_are_not_strict():
    f=history();mask=(f.ts>=at(11,30))&(f.ts<at(12,30));f.loc[mask,'low']=102.
    r=scan('US.SPY',f,at(12,32))
    assert not any(z['confirmed_at']==at(12,32).isoformat() for z in r['fvgs'])
    f=history();f.loc[f.ts.dt.date<pd.Timestamp('2026-10-29').date(),'high']=106.
    r=scan('US.SPY',f,at(11,32))
    assert not any(e['kind']=='MSS' for e in r['events'])


def test_missing_whole_session_cannot_supply_liquidity_or_pivot():
    f=history();f=f[f.ts.dt.date!=pd.Timestamp('2026-10-28').date()]
    r=scan('US.SPY',f,at(16,2))
    assert r['gap_count']>=7
    assert not any(e['kind']=='SWEEP' and e['status']=='CONFIRMED' and e['occurred_at'].startswith('2026-10-29') for e in r['events'])
