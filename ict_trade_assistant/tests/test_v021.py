from copy import deepcopy
from datetime import datetime
from desk.clock import ET, bounds
from desk.observations import build_observation, regions, ranked, price_basis_comparison
from desk.store import DEFAULTS


def test_regions_preserve_raw_and_merge_closed_intervals(market_fixture):
    o=build_observation('US.SPY',market_fixture,DEFAULTS,datetime(2026,10,30,8,tzinfo=ET))
    raw=deepcopy(o['monitors'])
    template=raw[0]
    o['monitors']=[dict(template,key=k,low=l,high=h,state="NEAR") for k,l,h in [('OR_5_HIGH',101,101),('OR_15_HIGH',101,101),('OR_30_HIGH',101,101),('MANUAL',101,102),('PDH',102.01,102.01)]]
    before=deepcopy(o['monitors'])
    rs=regions(o)
    assert len(rs)==2
    assert sorted(len(r['members']) for r in rs)==[1,4]
    assert o['monitors']==before
    assert len(ranked({'US.SPY':o,'US.VIX':dict(o,symbol='US.VIX')}))==1


def test_four_unique_symbols_no_fifth(market_fixture):
    obs={s:build_observation(s,market_fixture,DEFAULTS,datetime(2026,10,30,8,tzinfo=ET),dict(low=99,high=101)) for s in ['US.SPY','US.QQQ','US.IWM','US.SOXX','US.VIX']}
    rows=ranked(obs)
    assert len(rows)==4 and len({r['symbol'] for r in rows})==4


def test_price_basis_times_and_changed_rank(market_fixture):
    now=datetime(2026,10,30,8,tzinfo=ET)
    obs={s:build_observation(s,deepcopy(market_fixture),DEFAULTS,now,dict(low=99,high=101)) for s in ['US.SPY','US.QQQ']}
    v=obs['US.SPY']['close_verification']
    assert v['resolution']=='UNRESOLVED'
    assert v['native_daily_close_at'].endswith('16:00:00-04:00')
    assert v['last_minute_close_at'].endswith('16:00:00-04:00')
    obs['US.QQQ']['close_verification']['last_minute_close']=105
    rows=price_basis_comparison(obs)
    assert any(r['名次变化']!=0 for r in rows)
    assert all('日K进入候选' in r for r in rows)


def test_rth_edt_est_calendar():
    assert bounds(datetime(2026,10,30).date())[0].isoformat().endswith('09:30:00-04:00')
    assert bounds(datetime(2026,11,2).date())[0].isoformat().endswith('09:30:00-05:00')


def test_shared_database_windows_dedupe_and_no_trigger(market_fixture,tmp_path):
    from desk.store import Store
    from desk.observations import record_events
    from datetime import timedelta
    a=Store(tmp_path/'shared.db'); b=Store(tmp_path/'shared.db')
    now=datetime(2026,10,30,10,10,tzinfo=ET)
    o=build_observation('US.SPY',market_fixture,DEFAULTS,now)
    for row in o['monitors']: row['state']='OUTSIDE'
    record_events(a,o); record_events(b,o)
    assert a.table('market_events').empty
    o['monitors'][0]['state']='NEAR'
    o['monitors'][0]['quote_at']=(now+timedelta(seconds=1)).isoformat()
    record_events(a,o); record_events(b,o)
    assert len(a.table('market_events'))==1
    stale=build_observation('US.SPY',market_fixture,DEFAULTS,now+timedelta(seconds=91))
    record_events(b,stale)
    assert len(a.table('market_events'))==1
