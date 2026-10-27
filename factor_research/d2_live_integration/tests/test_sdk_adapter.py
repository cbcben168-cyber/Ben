import json
from types import SimpleNamespace
import pytest

from core import Inbox, Stop
from sdk_adapter import Adapter, context_type, handlers, proto_payload
from test_evidence import FakeClock


def response(stream):
    from futu.common.pb import Qot_Common_pb2 as q
    if stream=='TICKER':
        from futu.common.pb.Qot_GetTicker_pb2 import Response
        r=Response(retType=0); r.s2c.security.market=q.QotMarket_US_Security; r.s2c.security.code='SPY'
        t=r.s2c.tickerList.add(time='2026-10-27 09:45:00.123',sequence=7,dir=q.TickerDirection_Neutral,
                              price=600.,volume=2,turnover=1200.,recvTime=123.,type=0,pushDataType=0)
        t.hpVolume=2.5; t.timestamp=1793108700.123; t.typeSign=9
    else:
        from futu.common.pb.Qot_GetOrderBook_pb2 import Response
        r=Response(retType=0);r.s2c.security.market=q.QotMarket_US_Security;r.s2c.security.code='SPY'
        r.s2c.orderBookBidList.add(price=600.,volume=100,orederCount=3,hpVolume=100.5)
        r.s2c.orderBookAskList.add(price=600.01,volume=200,orederCount=4)
        r.s2c.svrRecvTimeBidTimestamp=1793108700.1
    return r


@pytest.mark.parametrize('stream',['TICKER','ORDER_BOOK'])
def test_actual_sdk_protobuf_callback_without_context(sdk,stream):
    inbox=Inbox(FakeClock()); h=handlers(sdk,inbox)[0 if stream=='TICKER' else 1]
    pb=response(stream);ret,_=h.on_recv_rsp(pb)
    assert ret==0 and inbox.fault is None
    e=inbox.q.get_nowait(); data=json.loads(e['decoded'])
    assert e['raw']==pb.SerializeToString() and data['protobuf_fields']['retType']==0
    if stream=='TICKER':
        row=data['native'][0]
        assert row['recv_timestamp']==123 and row['volume']==2.5
        assert data['protobuf_fields']['s2c']['tickerList'][0]['typeSign']==9
        assert row['ticker_direction']=='NEUTRAL'
    else:
        assert data['native']['Bid'][0][1]==100.5
        assert 'svrRecvTimeBid' not in data['protobuf_fields']['s2c']
        assert data['protobuf_fields']['s2c']['svrRecvTimeBidTimestamp']==1793108700.1


def test_callback_sdk_error_is_sanitized(sdk):
    box=Inbox(FakeClock());pb=response('TICKER');pb.retType=-1;pb.retMsg='account-secret'
    handlers(sdk,box)[0].on_recv_rsp(pb)
    assert box.fault=='PUSH_SDK_ERROR' and box.q.empty()


@pytest.mark.parametrize('stream',['TICKER','ORDER_BOOK'])
def test_actual_sync_unpack_hook_captures_fields_lost_by_public_table(sdk,monkeypatch,stream):
    pb=response(stream); box=Inbox(FakeClock())
    def init(self,**kw): self._OpenQuoteContext__security_firm=sdk.SecurityFirm.NONE
    monkeypatch.setattr(sdk.OpenQuoteContext,'__init__',init)
    monkeypatch.setattr(sdk.OpenQuoteContext,'get_sync_conn_id',lambda self:0)
    def processor(self,pack,unpack):return lambda **kw:unpack(pb)
    monkeypatch.setattr(sdk.OpenQuoteContext,'_get_sync_query_processor',processor)
    adapter=Adapter(box,sdk);adapter.ctx=context_type(sdk)(box)
    assert adapter.pull(stream)[0]==0
    data=json.loads(box.q.get_nowait()['decoded'])
    if stream=='TICKER':
        assert 'recv_timestamp' not in data['public']['columns']
        assert data['native'][0]['recv_timestamp']==123
    assert data['protobuf_fields'] is not None


def test_context_disables_initial_retry_and_reconnect(sdk,monkeypatch):
    base=sdk.OpenQuoteContext
    def init(self,**kw): self._auto_reconnect=True; self._init_connect_sync()
    def first(self): assert self._auto_reconnect is False; return 0
    monkeypatch.setattr(base,'__init__',init)
    monkeypatch.setattr(base,'_init_connect_sync',first)
    monkeypatch.setattr(base,'_connect_sync',lambda self:0)
    box=Inbox(FakeClock()); ctx=context_type(sdk)(box)
    ctx._connect_sync()
    with pytest.raises(Stop,match='SDK_RECONNECT_BLOCKED'):ctx._connect_sync()
    assert ctx.on_api_socket_reconnected()[0]==0
    assert ctx.on_api_socket_reconnected()[0]==-1
    with pytest.raises(Stop):ctx._wait_reconnect()


def test_only_own_subscription_and_state_whitelist(sdk):
    seen=[]
    class Mock:
        def get_global_state(self):return 0,{'qot_logined':True,'server_ver':'1010','user_id':'SECRET'}
        def query_subscription(self,**kw):seen.append(kw);return 0,{'own_used':2,'user_id':'SECRET'}
        def unsubscribe(self,*args,**kw):seen.append((args,kw));return 0,None
    a=Adapter(Inbox(FakeClock()),sdk);a.ctx=Mock()
    assert 'SECRET' not in json.dumps(a.state())
    a.subscription();a.unsubscribe()
    assert seen[0]=={'is_all_conn':False}
    assert seen[1][1]=={'unsubscribe_all':False} and seen[1][0][0]==['US.SPY']


def test_missing_protobuf_is_explicit():
    assert proto_payload(None)==(None,None)
