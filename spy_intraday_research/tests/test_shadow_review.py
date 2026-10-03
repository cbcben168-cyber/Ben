import json
import pandas as pd
import pytest
from spy_research import shadow
from spy_research.shadow import market_clock,Session,exclusive
from spy_research.review import daily,OBS_COLUMNS
from spy_research.storage import write_csv

@pytest.mark.parametrize('time,status',[('2026-10-03T14:00Z','CLOSED'),('2026-10-05T13:00Z','PREOPEN'),('2026-10-05T13:31Z','OPEN'),('2026-11-27T18:01Z','CLOSED')])
def test_market_calendar(time,status): assert market_clock(pd.Timestamp(time))[1]==status

def setup_session(tmp_path,monkeypatch):
    date='2026-10-02'; time=pd.date_range('2026-10-02 13:30',periods=5,freq='min',tz='UTC')
    bars=pd.DataFrame(dict(code='US.SPY',session_date=date,ts_start_utc=time,ts_end_utc=time+pd.Timedelta(minutes=1),open=100.,high=101.,low=99.,close=100.,volume=10.))
    event=pd.DataFrame([dict(event_id='signal',session_date=date,setup='ORB5',direction=1,ts_end_utc=time[-1]+pd.Timedelta(minutes=1),signal_time=time[-1]+pd.Timedelta(minutes=1))])
    monkeypatch.setattr(shadow,'build',lambda *a:pd.DataFrame({'session_date':[date]}))
    monkeypatch.setattr(shadow,'apply_states',lambda frame,*a:frame)
    monkeypatch.setattr(shadow,'detect',lambda *a:(pd.DataFrame(),event))
    lock=dict(version='diagnostic_v1',state_model={},horizon_minutes=30,additional_cost_bps=2,max_quote_age_seconds=10,max_signal_delay_seconds=10)
    runner=Session(tmp_path,lock,date,bars.iloc[:0],set())
    return runner,bars,pd.Timestamp('2026-10-02 13:35:03Z')

def test_signal_idempotence_and_restart(tmp_path,monkeypatch):
    runner,bars,now=setup_session(tmp_path,monkeypatch)
    quote=dict(timestamp=now,price=100.)
    runner.step(bars,quote,now); runner.step(bars,quote,now)
    restarted=Session(tmp_path,runner.lock,runner.date,bars.iloc[:0],set())
    restarted.step(bars,quote,now)
    assert len(restarted.events)==1 and len(restarted.observations)==1

def test_stale_quote_does_not_create_observation(tmp_path,monkeypatch):
    runner,bars,now=setup_session(tmp_path,monkeypatch)
    runner.step(bars,dict(timestamp=now-pd.Timedelta(minutes=1),price=100.),now)
    assert runner.observations.empty and runner.events.iloc[0].status=='DETECTED'

def test_gap_and_revision_pause(tmp_path,monkeypatch):
    runner,bars,now=setup_session(tmp_path,monkeypatch)
    assert runner.step(bars.iloc[1:],dict(timestamp=now,price=100.),now)=='PAUSED'
    runner.step(bars,dict(timestamp=now,price=100.),now)
    changed=bars.copy(); changed.loc[0,'volume']=11
    assert runner.step(changed,dict(timestamp=now,price=100.),now)=='PAUSED'

def test_exclusive_runner_lock(tmp_path):
    path=tmp_path/'runner.lock'
    with exclusive(path):
        with pytest.raises(ValueError):
            with exclusive(path): pass
    assert not path.exists()

def test_empty_day_report_and_idempotence(tmp_path):
    first=daily(tmp_path,'diagnostic_v1','2026-10-02')
    second=daily(tmp_path,'diagnostic_v1','2026-10-02')
    assert first==second
    assert json.loads((first/'review_manifest.json').read_text())['status']=='INSUFFICIENT'
    assert pd.read_csv(first/'optimization_decisions.csv').status.iloc[0]=='AWAITING_USER_CHOICE'

def test_losing_day_and_partial_censor_remain_in_report(tmp_path):
    folder=tmp_path/'artifacts/paper/diagnostic_v1/2026-10-02'
    records=pd.DataFrame([dict(event_id='a',session_date='2026-10-02',setup='ORB5',direction=1,status='COMPLETE',net_bps=-10),
                          dict(event_id='b',session_date='2026-10-02',setup='ORB5',direction=1,status='OPEN')],columns=OBS_COLUMNS)
    write_csv(folder/'observations.csv',records)
    report=daily(tmp_path,'diagnostic_v1','2026-10-02')
    metrics=pd.read_csv(report/'daily_metrics.csv').iloc[0]
    assert metrics.status=='PARTIAL' and metrics.net_mean_bps==-10 and metrics.executable_fills==0

def test_replay_is_distinct_from_future_report(tmp_path):
    report=daily(tmp_path,'replay_diagnostic_v2','2026-10-02')
    assert json.loads((report/'review_manifest.json').read_text())['mode']=='replay'
    assert '不是未来样本' in (report/'daily_review.md').read_text(encoding='utf-8')

def test_processing_delay_requires_new_quote(tmp_path,monkeypatch):
    runner,bars,now=setup_session(tmp_path,monkeypatch)
    runner.lock['account_processing_delay']=True
    runner.step(bars,dict(timestamp=now,price=100.),now)
    assert runner.observations.empty
    later=now+pd.Timedelta(seconds=5)
    runner.step(bars,dict(timestamp=later,price=100.1),later)
    assert len(runner.observations)==1

def test_invalid_live_prices_fail_closed(tmp_path,monkeypatch):
    runner,bars,now=setup_session(tmp_path,monkeypatch)
    bars.loc[0,'high']=50
    assert runner.step(bars,dict(timestamp=now,price=100.),now)=='PAUSED'
    assert runner.events.empty and runner.observations.empty
