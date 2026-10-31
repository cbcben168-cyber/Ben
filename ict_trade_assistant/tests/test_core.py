from datetime import datetime, timedelta, date
import pandas as pd
import pytest
from desk.clock import ET, bounds, session
from desk.analytics import normalize, key_levels, aggregate_rth, observe
from desk.provider import quote_quality, Provider
from desk.store import Store


def dt(text):
    return datetime.fromisoformat(text).replace(tzinfo=ET)


def minutes(day='2026-10-30', count=390):
    ts = pd.date_range(f'{day} 09:30', periods=count, freq='min')
    raw = pd.DataFrame(dict(time_key=ts.astype(str), open=100., high=102., low=99., close=101., volume=10.))
    return normalize(raw, '1M', dt(day+'T18:00'))


@pytest.mark.parametrize('day,offset,utc', [('2026-10-30',-4,13), ('2026-11-02',-5,14)])
def test_dst(day, offset, utc):
    op, close = bounds(date.fromisoformat(day))
    assert op.utcoffset().total_seconds() == offset*3600
    assert op.astimezone(__import__('datetime').timezone.utc).hour == utc
    assert (close-op).total_seconds() == 390*60


def test_holidays_early_close_sessions():
    assert bounds(date(2026,11,26)) is None
    assert bounds(date(2026,11,27))[1].hour == 13
    assert session(dt('2026-11-27T13:01')) == 'UNKNOWN'
    for clock, expected in [('04:00','PRE'),('09:30','RTH'),('16:00','AFTER'),('20:00','NIGHT')]:
        assert session(dt('2026-10-30T'+clock)) == expected


def test_or_missing_minutes_and_unfinished():
    f = minutes()
    now = dt('2026-10-30T10:03')
    levels = key_levels(f, now.date(), now)
    assert levels['OR_30']['high'] == 102
    assert levels['OR_30']['expected'] == 30
    broken = key_levels(f.drop(index=5), now.date(), now)
    assert broken['OR_30']['high'] is None
    assert key_levels(f, now.date(), dt('2026-10-30T09:59'))['OR_30']['high'] is None
    quarantined = normalize(pd.DataFrame(dict(time_key=['2026-10-30 09:30:00'], open=[100],high=[101],low=[99],close=[100],volume=[1])), '1M',dt('2026-10-30T09:32'))
    assert not quarantined.iloc[0].eligible


def test_aggregation_tail_and_session_isolation():
    f = minutes()
    now = dt('2026-10-30T18:00')
    bars = aggregate_rth(f,240,now)
    assert bars.duration_minutes.tolist() == [240,150]
    f.loc[0,'session'] = 'NIGHT'
    assert aggregate_rth(f,240,now).duration_minutes.tolist() == [150]
    early = aggregate_rth(minutes('2026-11-27',210),240,dt('2026-11-27T18:00'))
    assert early.duration_minutes.tolist() == [210]


def test_bad_ohlc_rejected():
    raw = pd.DataFrame(dict(time_key=['2026-10-30 09:30:00'],open=[100],high=[90],low=[99],close=[100],volume=[1]))
    with pytest.raises(ValueError):
        normalize(raw,'1M',dt('2026-10-30T12:00'))


def test_quality_and_alert_gates():
    now = dt('2026-10-30T10:00')
    row = dict(data_date='2026-10-30',data_time='09:59:55',last_price=100.)
    assert quote_quality(row,'LV1',now)['quality'] == 'AVAILABLE'
    assert quote_quality(row,'UNKNOWN',now)['quality'] == 'UNAVAILABLE'
    assert quote_quality(row,'LV1',now+timedelta(minutes=2))['quality'] == 'STALE'
    assert quote_quality(row,'LV1',now,20)['quality'] == 'UNAVAILABLE'
    zone = dict(low=100.,high=101.,invalid=99.,direction='LONG',stage='等待 MSS')
    assert observe(100,'STALE',zone,10)[0] == 'UNAVAILABLE'
    assert observe(100,'AVAILABLE',zone,10)[0] == '价格到达关注区域'
    assert observe(98,'AVAILABLE',zone,10)[0] == '失效'
    assert observe(99.95,'AVAILABLE',zone,10)[0] == '接近流动性区域'
    assert observe(110,'AVAILABLE',zone,10)[0] == '等待 MSS'


def test_sqlite_restart_and_dedupe(tmp_path):
    path = tmp_path/'desk.sqlite3'
    a = Store(path)
    a.save('distance_bps',20.)
    a.event('ALERT','US.SPY','test',dedupe='one')
    a.event('ALERT','US.SPY','test',dedupe='one')
    a.event('NOTE','US.SPY','note')
    a.bars('US.SPY',minutes(count=5),'1M')
    a.levels('US.SPY','2026-10-30',{'NIGHT':{'status':'UNAVAILABLE'}})
    b = Store(path)
    assert b.settings()['distance_bps'] == 20
    assert len(b.table('audit')) == 1
    assert len(b.table('events')) == 2
    with b.connect() as c:
        assert c.execute('SELECT count(*) FROM bars').fetchone()[0] == 5
        assert c.execute('SELECT count(*) FROM levels').fetchone()[0] == 1


def test_provider_disconnect(monkeypatch):
    p = Provider()
    def fail():
        raise ConnectionRefusedError()
    monkeypatch.setattr(p,'connect',fail)
    result = p.fetch('US.SPY')
    assert result['health']['quality'] == 'UNAVAILABLE'
    assert result['minute'].empty


def test_provider_boolean_login_permission_whitelist(monkeypatch):
    class Quotes:
        def get_global_state(self):
            return 0, dict(qot_logined=True, timestamp=dt('2026-10-30T10:00').timestamp())
        def get_user_info(self):
            return 0, dict(us_qot_right='LV3', web_key='DO_NOT_PERSIST_TEST_VALUE')
        def subscribe(self,*args,**kwargs):
            return 0, None
        def get_stock_quote(self,*args):
            return 0, pd.DataFrame([dict(data_date='2026-10-30',data_time='09:59:55',last_price=100.)])
    p = Provider()
    p.ctx = Quotes()
    monkeypatch.setattr('desk.provider.now_et',lambda:dt('2026-10-30T10:00'))
    monkeypatch.setattr(p,'history',lambda *a:(pd.DataFrame(),True))
    result = p.fetch('US.SPY')
    assert result['health']['quality'] == 'AVAILABLE'
    assert result['health']['right'] == 'LV3'
    assert 'DO_NOT_PERSIST_TEST_VALUE' not in str(result)
    assert result['daily_pagination_complete']
