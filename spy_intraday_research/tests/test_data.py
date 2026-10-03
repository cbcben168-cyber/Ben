import pandas as pd
import pytest
from spy_research.data import schedule, normalize, quality, aggregate5

def fixture(day):
    session = schedule(day,day).iloc[0]
    times = pd.date_range(session.open,session.close,freq='min',inclusive='left').tz_convert('America/New_York')
    return pd.DataFrame(dict(code='US.SPY',time_key=times.strftime('%Y-%m-%d %H:%M:%S'),
                             open=100.,high=102.,low=99.,close=101.,volume=10,turnover=1000))

@pytest.mark.parametrize('day,count',[('2026-10-02',390),('2026-11-27',210)])
def test_full_and_half_day(day,count):
    good, report = quality(normalize(fixture(day)),day,day)
    assert report.iloc[0].status == 'PASS'
    assert len(good)==count
    five=aggregate5(good)
    assert len(five)==count//5
    assert (five.volume==50).all()
    assert (five.turnover==5000).all()

def test_dst():
    before=schedule('2026-03-06','2026-03-06').iloc[0].open
    after=schedule('2026-03-09','2026-03-09').iloc[0].open
    assert before.hour==14 and after.hour==13

def test_missing_is_quarantined():
    frame=normalize(fixture('2026-10-02').iloc[1:])
    good, report=quality(frame,'2026-10-02','2026-10-02')
    assert good.empty and report.iloc[0].missing==1

def test_duplicates():
    raw=fixture('2026-10-02')
    assert len(normalize(pd.concat([raw,raw.iloc[:1]])))==390
    bad=raw.iloc[:1].copy(); bad['close']=100
    with pytest.raises(ValueError,match='CONFLICTING'):
        normalize(pd.concat([raw,bad]))

def test_invalid_prices():
    raw=fixture('2026-10-02'); raw.loc[0,'close']=float('inf')
    good, report=quality(normalize(raw),'2026-10-02','2026-10-02')
    assert good.empty and report.iloc[0].invalid==1

def test_aggregation_and_incomplete():
    frame=normalize(fixture('2026-10-02'))
    five=aggregate5(frame)
    assert five.iloc[0].open==100 and five.iloc[0].close==101
    assert five.iloc[0].ts_end_utc-frame.iloc[0].ts_start_utc==pd.Timedelta(minutes=5)
    with pytest.raises(ValueError): aggregate5(frame.iloc[1:])

def test_input_order_invariant():
    raw=fixture('2026-10-02')
    pd.testing.assert_frame_equal(normalize(raw),normalize(raw.sample(frac=1,random_state=3)))

def test_future_append_preserves_past():
    raw=fixture('2026-10-02')
    joined=normalize(pd.concat([raw,fixture('2026-10-05')]))
    pd.testing.assert_frame_equal(normalize(raw),joined[joined.session_date=='2026-10-02'].reset_index(drop=True))

def test_end_timestamp_contract():
    raw=fixture('2026-10-02')
    raw.time_key=(pd.to_datetime(raw.time_key)+pd.Timedelta(minutes=1)).dt.strftime('%Y-%m-%d %H:%M:%S')
    good, report=quality(normalize(raw,'end'),'2026-10-02','2026-10-02')
    assert len(good)==390 and report.iloc[0].status=='PASS'
