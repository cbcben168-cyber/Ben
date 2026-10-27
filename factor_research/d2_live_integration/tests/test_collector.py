import json
from pathlib import Path
import pytest

from core import Stop, WINDOW, write_once, encoded
from collector import collect, Calls
from test_evidence import FakeClock, ticker, book


class FakeAdapter:
    def __init__(self, inbox, reject=None, exception=None):
        self.inbox=inbox; self.reject=reject; self.exception=exception; self.calls=[]; self.closed=False
        self.subscribe_at=None
        inbox.clock.hook=self.push

    def result(self,name,data=None):
        self.calls.append(name)
        if self.exception==name: raise RuntimeError('secret-account-DO-NOT-LOG')
        return (-1,'secret-account-DO-NOT-LOG') if self.reject==name else (0,data or {})

    def connect(self):return self.result('connect')
    def state(self):return self.result('state',{'qot_logined':True,'server_ver':'1010'})
    def subscription(self):return self.result('subscription',{'own_used':2})
    def subscribe(self):
        self.subscribe_at=self.inbox.clock.mono
        return self.result('subscribe')
    def pull(self,stream):
        ret,data=self.result('pull_'+stream)
        if ret==0:self.inbox.submit(stream,[ticker(777)] if stream=='TICKER' else book(),b'pull')
        return ret,data
    def unsubscribe(self):return self.result('unsubscribe')
    def close(self):self.closed=True;return self.result('close')
    def push(self):
        if self.subscribe_at is None:return
        c=self.inbox.clock
        if c.wall.isoformat()>='2026-10-27T17:15:00+00:00':
            self.inbox.submit('TICKER',[ticker(c.mono)],b'tick')
            self.inbox.submit('ORDER_BOOK',book(600+(c.mono//1_000_000_000)%30*.01),b'book')


def run(tmp_path, reject=None, exception=None, c=None, limits=None, factory_extra=None):
    write_once(tmp_path/'INVOCATION_ONCE.json',b'{}')
    c=c or FakeClock(); keep=[]
    def factory(box):
        a=FakeAdapter(box,reject,exception);keep.append(a)
        if factory_extra:factory_extra(a)
        return a
    out=collect(tmp_path,{'window':WINDOW,'expected_opend_version':'1010'},c,factory,lambda:None,limits)
    return out,keep[0]


def test_complete_300s_flow_and_nine_calls(tmp_path):
    out,a=run(tmp_path)
    assert out['status']=='COMPLETE' and out['reason']=='WINDOW_COMPLETE'
    assert out['minimum_usable'] and out['observation_tickers']>=100 and out['observation_book_versions']>=20
    assert len(out['calls_used'])==9 and len(set(out['calls_used']))==9
    assert a.calls.count('pull_TICKER')==a.calls.count('pull_ORDER_BOOK')==1
    assert a.closed and out['entitlement']=='NOT_VERIFIED'
    assert out['mode']=='SYNTHETIC' and out['edge_status']=='NOT_TESTED'


@pytest.mark.parametrize('slot', ['connect','state','subscription','subscribe','pull_TICKER','pull_ORDER_BOOK'])
def test_rejection_no_retry_or_sensitive_error(tmp_path,slot):
    out,a=run(tmp_path,reject=slot)
    assert out['status']=='PARTIAL' and out['reason']=='PERMISSION_OR_SDK_REJECTED'
    assert a.calls.count(slot)==1
    assert b'secret-account' not in b''.join(p.read_bytes() for p in tmp_path.iterdir())
    assert len(out['calls_used'])<=9


def test_sdk_exception_cleanup_and_redaction(tmp_path):
    out,a=run(tmp_path,exception='subscribe')
    assert out['reason']=='SDK_EXCEPTION' and a.closed
    assert 'unsubscribe' not in a.calls
    assert b'secret-account' not in b''.join(p.read_bytes() for p in tmp_path.iterdir())


@pytest.mark.parametrize('reason', ['DISCONNECTED','SDK_RECONNECT_BLOCKED','CONNECTION_EPOCH_CHANGED'])
def test_disconnect_stops_without_reconnect(tmp_path,reason):
    out,a=run(tmp_path,factory_extra=lambda a:a.inbox.fail(reason))
    assert out['status']=='PARTIAL' and out['reason']==reason and a.closed
    assert a.calls.count('connect')==1


def test_no_push_still_only_two_pulls(tmp_path):
    out,a=run(tmp_path,factory_extra=lambda a:setattr(a.inbox.clock,'hook',None))
    assert out['status']=='COMPLETE' and not out['minimum_usable'], out
    assert a.calls.count('pull_TICKER')==a.calls.count('pull_ORDER_BOOK')==1


def test_limits_partial_and_close(tmp_path):
    from core import Limits
    out,a=run(tmp_path,limits=Limits(records=3))
    assert out['status']=='PARTIAL' and out['reason']=='RESOURCE_LIMIT' and a.closed


def test_calls_duplicate_slot_and_slow_result(tmp_path):
    from core import Guard
    c=FakeClock(); calls=Calls(tmp_path,c,Guard(c))
    calls.invoke('state',lambda:(0,{}))
    with pytest.raises(Stop,match='SDK_BUDGET'):calls.invoke('state',lambda:(0,{}))
    def slow():c.advance(6);return 0,{}
    with pytest.raises(Stop,match='SDK_TIMEOUT'):calls.invoke('connect',slow)


def test_tcp_refusal_consumes_attempt_without_sdk(tmp_path):
    write_once(tmp_path/'INVOCATION_ONCE.json',b'{}')
    touched=[]
    def refuse():raise Stop('TCP_UNAVAILABLE')
    out=collect(tmp_path,{'window':WINDOW},FakeClock(),lambda b:touched.append(b),refuse)
    assert out['reason']=='TCP_UNAVAILABLE' and not touched
    assert (tmp_path/'INVOCATION_ONCE.json').exists() and not out['calls_used']


def test_preflight_overruns_window_no_observation(tmp_path):
    def extra(a):
        # Simulate slow local SDK import before the first network Context constructor.
        a.inbox.clock.advance(41)
    out,a=run(tmp_path,c=FakeClock('2026-10-27T17:14:20+00:00'),factory_extra=extra)
    assert out['status']=='PARTIAL' and out['reason']=='PREFLIGHT_LATE'
    assert 'connect' not in a.calls and 'ticker_pull' not in out['calls_used']


def test_worker_fsync_failure_is_not_success(tmp_path,monkeypatch):
    import core
    write_once(tmp_path/'INVOCATION_ONCE.json',b'{}')
    monkeypatch.setattr(core.os,'fsync',lambda fd:(_ for _ in ()).throw(OSError('full')))
    out=collect(tmp_path,{'window':WINDOW},FakeClock(),FakeAdapter,lambda:None)
    assert out['status']=='PARTIAL' and out['reason']=='PERSISTENCE_NOT_VERIFIED'


@pytest.mark.parametrize('which',['close','unsubscribe'])
def test_cleanup_rejection_not_reported_as_complete(tmp_path,which):
    out,a=run(tmp_path,reject=which)
    assert out['status']=='PARTIAL' and out['cleanup_errors']

