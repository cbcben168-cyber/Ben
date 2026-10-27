from datetime import datetime, timedelta, timezone
import json
import queue
import pytest

import core
from core import Evidence, Guard, Inbox, Limits, Stop, encoded, inspect_market, source_time, verify_receipts


class FakeClock:
    def __init__(self, value='2026-10-27T17:14:00+00:00'):
        self.wall = datetime.fromisoformat(value); self.mono = 1_000_000_000
        self.hook = None

    def stamp(self):
        return {'utc': self.wall.isoformat(), 'monotonic_ns': self.mono}

    def advance(self, seconds):
        self.wall += timedelta(seconds=seconds); self.mono += int(seconds*1e9)

    def sleep(self, seconds):
        self.advance(max(seconds, 1))
        if self.hook: self.hook()


def ticker(sequence=1, **fields):
    return dict(code='US.SPY', sequence=sequence, time='2026-10-27 13:15:00.000',
                price=600., volume=2., turnover=1200., ticker_direction='NEUTRAL',
                type='ODD_LOT', recv_timestamp=123., extra_field={'keep': True}, **fields)


def book(price=600.):
    return dict(code='US.SPY', name='SPY', order_book_type='NORMAL',
                Bid=[[price, 100., 2, {'orderA': 100}]], Ask=[[price+.01, 200., 3, {}]],
                svr_recv_time_bid='', svr_recv_time_ask='', extra_field='preserved')


def envelope(inbox, stream='TICKER', native=None, raw=b'raw-pb'):
    inbox.submit(stream, native if native is not None else [ticker()], raw,
                 {'protocol_optional': 'kept'})
    return inbox.q.get_nowait()


def test_receipts_fields_hash_and_fsync(tmp_path, monkeypatch):
    clock = FakeClock(); box = Inbox(clock); e = envelope(box)
    calls = []; original = core.os.fsync
    monkeypatch.setattr(core.os, 'fsync', lambda fd: (calls.append(fd), original(fd))[-1])
    store = Evidence(tmp_path, clock); store.accept(e, True)
    stored = json.loads((tmp_path/'response_000001.json').read_bytes())
    assert stored['native'][0]['extra_field'] == {'keep': True}
    assert stored['native'][0]['ticker_direction'] == 'NEUTRAL'
    assert stored['native'][0]['recv_timestamp'] == 123.
    assert stored['protobuf_fields']['protocol_optional'] == 'kept'
    assert (tmp_path/'response_000001.pb').read_bytes() == b'raw-pb'
    assert len(calls) == 3
    assert verify_receipts(tmp_path)['receipt_head'] == store.head
    receipt = json.loads((tmp_path/'receipts.jsonl').read_bytes())
    assert len(receipt['receipt_sha256']) == 64
    assert receipt['quality'][0]['direction_interpretation'] == 'UNVERIFIED_VENDOR_FIELD'


def test_raw_tamper_is_detected(tmp_path):
    clock = FakeClock(); s = Evidence(tmp_path, clock)
    s.accept(envelope(Inbox(clock)))
    (tmp_path/'response_000001.pb').write_bytes(b'changed')
    with pytest.raises(Stop, match='RAW_HASH_MISMATCH'): verify_receipts(tmp_path)


def test_missing_raw_is_not_fabricated(tmp_path):
    c = FakeClock(); s = Evidence(tmp_path, c)
    s.accept(envelope(Inbox(c), raw=None))
    row = json.loads((tmp_path/'receipts.jsonl').read_bytes())
    assert row['raw_status'] == 'NOT_AVAILABLE'
    assert not (tmp_path/'response_000001.pb').exists()
    assert s.summary(True)['minimum_usable'] is False


def test_duplicate_tickers_and_book_versions(tmp_path):
    c = FakeClock(); s = Evidence(tmp_path, c); box = Inbox(c)
    for stream, data in [('TICKER',[ticker()]), ('TICKER',[ticker()]),
                         ('ORDER_BOOK',book()), ('ORDER_BOOK',book()), ('ORDER_BOOK',book(601.))]:
        s.accept(envelope(box, stream, data), True)
    assert s.count == 5 and len(s.seen_ticks) == 1 and len(s.seen_books) == 2
    assert s.duplicate_tickers == 1 and s.duplicate_books == 1
    assert verify_receipts(tmp_path)['messages'] == 5


@pytest.mark.parametrize('stream,data,reason', [
    ('TICKER', [], 'EMPTY_MARKET_DATA'),
    ('TICKER', [dict(ticker(), code='US.QQQ')], 'WRONG_SYMBOL'),
    ('TICKER', [dict(ticker(), price=-1)], 'INVALID_TICKER'),
    ('TICKER', [dict(ticker(), volume=float('nan'))], 'INVALID_TICKER'),
    ('ORDER_BOOK', dict(book(), Bid=[]), 'EMPTY_BOOK'),
    ('ORDER_BOOK', dict(book(), Ask=[[599.,1,1,{}]]), 'CROSSED_BOOK'),
    ('ORDER_BOOK', dict(book(), Ask=[[601.,-1,1,{}]]), 'INVALID_BOOK_LEVEL')])
def test_invalid_market_is_saved_then_stops(tmp_path, stream, data, reason):
    c = FakeClock(); s = Evidence(tmp_path,c)
    with pytest.raises(Stop, match=reason): s.accept(envelope(Inbox(c),stream,data))
    assert (tmp_path/'response_000001.json').exists()
    assert json.loads((tmp_path/'receipts.jsonl').read_bytes())['invalid_reason']


def test_queue_limit_no_silent_drop():
    c=FakeClock(); b=Inbox(c, Limits(queue_size=1))
    envelope(b)  # empty it again
    b.submit('TICKER',[ticker()],b'x'); b.submit('TICKER',[ticker(2)],b'y')
    assert b.fault == 'QUEUE_LIMIT' and b.q.qsize()==1
    assert json.loads(b.q.get()['decoded'])['native'][0]['sequence']==1


def test_message_limit():
    b=Inbox(FakeClock(),Limits(message_bytes=4))
    b.submit('TICKER',[ticker()],b'x'*5)
    assert b.fault=='MESSAGE_LIMIT' and b.q.empty()


@pytest.mark.parametrize('limits', [Limits(records=1), Limits(market_bytes=32)])
def test_resource_cap_keeps_whole_batch_unstored(tmp_path, limits):
    c=FakeClock(); s=Evidence(tmp_path,c,limits); b=Inbox(c)
    with pytest.raises(Stop, match='RESOURCE_LIMIT'):
        s.accept(envelope(b,native=[ticker(),ticker(2)]))
    assert not list(tmp_path.glob('response*'))
    assert json.loads((tmp_path/'UNSTORED_BATCH.json').read_bytes())['records']==2


def test_exact_record_limit_stops_after_preserving_batch(tmp_path):
    c=FakeClock(); s=Evidence(tmp_path,c,Limits(records=1))
    with pytest.raises(Stop,match='RESOURCE_LIMIT'): s.accept(envelope(Inbox(c)))
    assert verify_receipts(tmp_path)['messages']==1


def test_fsync_failure_never_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(core.os,'fsync',lambda fd: (_ for _ in ()).throw(OSError('synthetic')))
    with pytest.raises(OSError): Evidence(tmp_path,FakeClock()).accept(envelope(Inbox(FakeClock())))
    assert not (tmp_path/'receipts.jsonl').exists()


@pytest.mark.parametrize('evidence', [None, {'qualified': False},
    {'qualified': True, 'observed_at_utc':'2026-10-27T17:10:00+00:00','error_bound_seconds':.1,'offset_seconds':0},
    {'qualified': True, 'observed_at_utc':'2026-10-27T17:15:00+00:00','error_bound_seconds':.1,'offset_seconds':2}])
def test_unqualified_clock_source_age_is_null(evidence):
    out=source_time('2026-10-27 13:15:00',FakeClock('2026-10-27T17:15:01+00:00').stamp(),evidence,'America/New_York')
    assert out['source_age_ms'] is None and not out['timeliness_pass']


def test_missing_book_time_and_semantics_not_assumed():
    r=inspect_market('ORDER_BOOK', book(), FakeClock().stamp())[0]
    assert r['bid_time']['source_age_ms'] is None and r['nbbo_status']=='NOT_VERIFIED'
    e={'qualified':True,'observed_at_utc':'2026-10-27T17:15:00+00:00','error_bound_seconds':.2,'offset_seconds':0}
    r=source_time('2026-10-27 13:15:00',FakeClock('2026-10-27T17:15:01+00:00').stamp(),e,'America/New_York')
    assert r['source_age_ms']==1000 and r['conservative_upper_ms']==1200 and r['timeliness_pass']


@pytest.mark.parametrize('text', ['2026-11-01 01:30:00', 'invalid'])
def test_ambiguous_or_invalid_source_time_not_verified(text):
    r=source_time(text,FakeClock().stamp(),None,'America/New_York')
    assert not r['timeliness_pass'] and r['source_age_ms'] is None


def test_sequence_jump_not_called_packet_loss(tmp_path):
    c=FakeClock(); s=Evidence(tmp_path,c)
    s.accept(envelope(Inbox(c),native=[ticker(1),ticker(99)]))
    assert s.invalid==0 and len(s.seen_ticks)==2


def test_clock_jump_and_late_launch():
    c=FakeClock(); g=Guard(c); g.launch(); c.wall+=timedelta(seconds=2)
    with pytest.raises(Stop,match='CLOCK_JUMP'):g.check()
    with pytest.raises(Stop,match='LAUNCH_WINDOW'):Guard(FakeClock('2026-10-27T17:14:21+00:00')).launch()


def test_manifest_reserve_counts_toward_total_cap(tmp_path):
    c=FakeClock();s=Evidence(tmp_path,c,Limits(total_bytes=4*1024*1024))
    with pytest.raises(Stop,match='RESOURCE_LIMIT'):s.accept(envelope(Inbox(c)))
    assert s.count==0 and (tmp_path/'UNSTORED_BATCH.json').exists()


def test_epoch_and_stream_scope_fail_closed(tmp_path):
    c=FakeClock();s=Evidence(tmp_path,c);e=envelope(Inbox(c));e['epoch']=2
    with pytest.raises(Stop,match='CONNECTION_EPOCH_CHANGED'):s.accept(e)
    with pytest.raises(Stop,match='UNAUTHORIZED_STREAM'):inspect_market('QUOTE',book(),c.stamp())


def test_stale_and_negative_source_age_never_pass():
    c=FakeClock('2026-10-27T17:15:03+00:00')
    proof={'qualified':True,'observed_at_utc':c.stamp()['utc'],'error_bound_seconds':.1,'offset_seconds':0}
    stale=source_time('2026-10-27 13:15:00',c.stamp(),proof,'America/New_York')
    future=source_time('2026-10-27 13:15:05',c.stamp(),proof,'America/New_York')
    assert stale['source_age_ms']==3000 and not stale['timeliness_pass']
    assert future['status']=='NEGATIVE_AGE' and not future['timeliness_pass']


def test_nonmonotone_sequence_kept_without_claiming_lost_packets(tmp_path):
    c=FakeClock();s=Evidence(tmp_path,c)
    s.accept(envelope(Inbox(c),native=[ticker(99),ticker(1)]))
    r=json.loads((tmp_path/'receipts.jsonl').read_bytes())
    assert s.count==2 and s.nonmonotone_tickers==1
    assert r['quality'][1]['sequence_gap_interpretation']=='NOT_PACKET_LOSS_EVIDENCE'
