"""Instance-local Futu quote adapter. Loading this file never imports Futu or connects."""
from __future__ import annotations

import importlib
import sys
import types

from core import Stop, require, payload


def load_sdk():
    """Suppress SDK's unsolicited shared log/identity writes before package import.

    Replacement is process-local, not an installed SDK edit. D2 receipts are the log.
    No HOME/APPDATA reassignment, credentials or arbitrary SDK diagnostic text.
    """
    if 'futu' not in sys.modules:
        module = types.ModuleType('futu.common.ft_logger')
        class Quiet:
            BOTH_FILE_CONSOLE = 3; ONLY_FILE = 1; ONLY_CONSOLE = 2
            def __getattr__(self, name):
                return lambda *args, **kwargs: None
        module.logger = Quiet(); module.FTLog = Quiet
        module.__all__ = ['logger', 'FTLog']
        module.d2_silent = True
        sys.modules[module.__name__] = module
    require(getattr(sys.modules.get('futu.common.ft_logger'), 'd2_silent', False), 'SDK_LOGGING_NOT_ISOLATED')
    return importlib.import_module('futu')


def proto_payload(pb):
    if pb is None or not hasattr(pb, 'SerializeToString'):
        return None, None
    from google.protobuf.json_format import MessageToDict
    raw = pb.SerializeToString()
    fields = MessageToDict(pb, preserving_proto_field_name=True)
    return raw, fields


def handlers(sdk, inbox):
    def make(base, stream):
        class Handler(base):
            def on_recv_rsp(self, pb):
                stamp = inbox.clock.stamp()
                try:
                    raw, fields = proto_payload(pb)
                    ret, native = self.parse_rsp_pb(pb)
                    if ret != 0:
                        inbox.fail('PUSH_SDK_ERROR')
                    else:
                        inbox.submit(stream, native, raw, fields, received=stamp)
                    return ret, None
                except Exception:
                    inbox.fail('PUSH_DECODE_FAILED')
                    return -1, None
        return Handler()
    return (make(sdk.TickerHandlerBase, 'TICKER'), make(sdk.OrderBookHandlerBase, 'ORDER_BOOK'))


def context_type(sdk):
    class Quote(sdk.OpenQuoteContext):
        def __init__(self, inbox):
            self.d2_inbox = inbox
            self.d2_connects = 0
            self.d2_epoch = 0
            self.d2_pull = None
            super().__init__(host='127.0.0.1', port=11111, is_encrypt=False, is_async_connect=False)

        def _init_connect_sync(self):
            # Base __init__ first sets True; override before any initial connection.
            self._auto_reconnect = False
            return super()._init_connect_sync()

        def _connect_sync(self):
            self.d2_connects += 1
            require(self.d2_connects == 1, 'SDK_RECONNECT_BLOCKED')
            return super()._connect_sync()

        def _wait_reconnect(self, *args, **kwargs):
            self.d2_inbox.fail('SDK_RECONNECT_BLOCKED')
            raise Stop('SDK_RECONNECT_BLOCKED')

        def on_api_socket_reconnected(self):
            self.d2_epoch += 1
            if self.d2_epoch != 1:
                self.d2_inbox.fail('CONNECTION_EPOCH_CHANGED')
                return -1, 'D2_RECONNECT_BLOCKED'
            # Do not execute SDK automatic re-subscription even on reconnect.
            return 0, ''

        def on_disconnect(self, conn_id, reason, msg):
            if not getattr(self, 'd2_closing', False):
                self.d2_inbox.fail('DISCONNECTED')
            self._auto_reconnect = False
            return super().on_disconnect(conn_id, reason, '')

        def _get_sync_query_processor(self, pack_func, unpack_func):
            owner = getattr(getattr(unpack_func, '__self__', None), '__name__', '')
            if owner not in ('TickerQuery', 'OrderBookQuery'):
                return super()._get_sync_query_processor(pack_func, unpack_func)
            def unpack(pb):
                stamp = self.d2_inbox.clock.stamp()
                raw, fields = proto_payload(pb)
                result = unpack_func(pb)
                self.d2_pull = (raw, fields, result, stamp)
                return result
            return super()._get_sync_query_processor(pack_func, unpack)
    return Quote


class Adapter:
    def __init__(self, inbox, sdk=None):
        self.sdk = sdk or load_sdk()
        self.inbox = inbox
        self.ctx = None

    def connect(self):
        self.ctx = context_type(self.sdk)(self.inbox)
        require(self.ctx.d2_epoch == 1, 'INITIAL_CONNECTION_FAILED')
        for h in handlers(self.sdk, self.inbox):
            require(self.ctx.set_handler(h) == 0, 'HANDLER_REGISTRATION_FAILED')
        return 0, {'context': 'INDEPENDENT_QUOTE_ONLY'}

    def state(self):
        ret, data = self.ctx.get_global_state()
        if ret != 0:
            return ret, {'reason': 'STATE_QUERY_REJECTED'}
        # Never persist user_id or original full state dictionary.
        return ret, {k: data.get(k) for k in ('qot_logined', 'server_ver', 'server_build')}

    def subscription(self):
        ret, data = self.ctx.query_subscription(is_all_conn=False)
        if ret != 0:
            return ret, {'reason': 'SUBSCRIPTION_QUERY_REJECTED'}
        return ret, {k: data.get(k) for k in ('own_used', 'remain', 'total_used', 'sub_list')}

    def subscribe(self):
        return self.ctx.subscribe(['US.SPY'], [self.sdk.SubType.TICKER, self.sdk.SubType.ORDER_BOOK],
                                  is_first_push=False, subscribe_push=True,
                                  is_detailed_orderbook=False, session=self.sdk.Session.RTH)

    def pull(self, stream):
        self.ctx.d2_pull = None
        if stream == 'TICKER':
            ret, data = self.ctx.get_rt_ticker('US.SPY', num=100)
        else:
            ret, data = self.ctx.get_order_book('US.SPY', num=1)
        if ret == 0:
            captured = self.ctx.d2_pull
            if captured:
                raw, fields, result, received = captured
                self.inbox.submit(stream, result[2], raw, fields, origin='pull',
                                  public=payload(data), received=received)
            else:
                # Public-only fallback is explicit, never fabricated protobuf.
                native = data.to_dict('records') if hasattr(data, 'to_dict') else data
                self.inbox.submit(stream, native, origin='pull', public=payload(data))
        return ret, {'result': 'PULL_RECEIVED' if ret == 0 else 'PULL_REJECTED'}

    def unsubscribe(self):
        return self.ctx.unsubscribe(['US.SPY'], [self.sdk.SubType.TICKER, self.sdk.SubType.ORDER_BOOK],
                                    unsubscribe_all=False)

    def close(self):
        if self.ctx is not None:
            self.ctx.d2_closing = True
            self.ctx.close()
        return 0, {'closed': True}
