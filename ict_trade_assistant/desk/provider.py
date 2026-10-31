"""Only quote APIs. No trade context, account query, or order API."""
from datetime import timedelta
import math
import socket
import threading
import time
import logging
import pandas as pd
from .clock import ET, now_et, session
from .analytics import normalize


def quote_quality(row, right, now, server_skew=0):
    ts = pd.Timestamp(f"{row['data_date']} {row['data_time']}").tz_localize('America/New_York', ambiguous='raise', nonexistent='raise')
    price = float(row['last_price'])
    age = (now-ts).total_seconds()
    quality = 'AVAILABLE'
    reason = 'RTH 时间戳与权限检查通过；价格为供应商报价'
    if right not in ('LV1', 'LV2', 'LV3'):
        quality, reason = 'UNAVAILABLE', '实时权限未验证或权限不足'
    elif not math.isfinite(price) or price <= 0 or age < -5 or abs(server_skew) > 5:
        quality, reason = 'UNAVAILABLE', '价格或时钟检查失败'
    elif age > 90:
        quality, reason = 'STALE', '报价超过 90 秒；停盘/闭市也不会伪装实时'
    elif session(now) != 'RTH' or session(ts) != 'RTH':
        quality, reason = 'UNAVAILABLE', '扩展时段独立时间戳未验证；不使用 RTH last_price 触发提醒'
    return dict(quality=quality, reason=reason, price=price, quote_at=str(ts),
                received_at=now.isoformat(), age_seconds=round(age, 3), session=session(ts),
                source='FUTU_OPEND / get_stock_quote / last_price', right=right,
                server_clock_skew_seconds=server_skew)


class Provider:
    def __init__(self):
        self.ctx = None
        self.lock = threading.Lock()
        self.subscribed=set()
        self.history_cache={}
        self.next_connect=0
        self.connect_failures=0

    def close(self):
        if self.ctx is not None:
            self.ctx.close()
            self.ctx = None
        self.subscribed.clear()

    def reset_connection(self):
        with self.lock:
            self.close();self.connect_failures=0;self.next_connect=0

    def connect(self):
        import futu as ft
        with socket.create_connection(('127.0.0.1', 11111), timeout=2):
            pass
        if time.monotonic()<self.next_connect or self.connect_failures>=3:
            raise ConnectionError('有限重连已暂停，请使用诊断入口重新尝试')
        self.ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111, is_async_connect=True)
        self.ctx.set_sync_query_connect_timeout(5)

    def fetch(self, symbol):
        with self.lock:
            return self._fetch(symbol)

    def _fetch(self, symbol):
        import futu as ft
        received = now_et()
        result = dict(health=dict(quality='UNAVAILABLE', reason='OpenD 未连接', right='UNKNOWN',
                                 source='FUTU_OPEND', received_at=received.isoformat()),
                      minute=pd.DataFrame(), daily=pd.DataFrame(), errors=[], opend_status='UNAVAILABLE')
        try:
            if self.ctx is None:
                self.connect()
            ret, state = self.ctx.get_global_state()
            if ret != ft.RET_OK:
                result['health']['reason'] = 'OpenD 全局状态读取失败 / DISCONNECTED'
                self.connect_failures+=1
                self.next_connect=time.monotonic()+min(30,2**self.connect_failures)
                self.close()
                return result
            if state.get('qot_logined') not in (True, 1, '1'):
                result['health']['reason'] = 'OpenD 行情服务未登录 / NOT_LOGGED_IN'
                return result
            self.connect_failures=0
            result['opend_status']='CONNECTED'
            skew = float(state['timestamp']) - received.timestamp()
            ret, user = self.ctx.get_user_info()
            # Whitelist permission only. Never log/persist returned identity or web_key.
            right = user.get('us_qot_right', 'UNKNOWN') if ret == ft.RET_OK else 'UNKNOWN'
            result['health']['right'] = right
            if symbol not in self.subscribed:
                ret, _ = self.ctx.subscribe([symbol], [ft.SubType.QUOTE], subscribe_push=False, session=ft.Session.RTH)
                if ret == ft.RET_OK:self.subscribed.add(symbol)
            else:ret=ft.RET_OK
            if ret == ft.RET_OK:
                ret, quotes = self.ctx.get_stock_quote([symbol])
                if ret == ft.RET_OK and not quotes.empty:
                    result['health'] = quote_quality(quotes.iloc[0], right, now_et(), skew)
                else:
                    result['errors'].append('报价不可用：OpenD 拒绝或无数据')
            else:
                result['errors'].append('QUOTE 订阅失败：请检查美股行情权限或订阅额度')
            for period, kind, days, sess in [('minute', ft.KLType.K_1M, 7, ft.Session.ALL),
                                              ('daily', ft.KLType.K_DAY, 120, ft.Session.RTH)]:
                try:
                    cache_key=(symbol,period)
                    saved=self.history_cache.get(cache_key)
                    ttl=60 if period=='minute' else 1800
                    if saved and time.monotonic()-saved[0]<ttl:
                        _,frame,complete=saved
                        result[period]=frame.copy(deep=True)
                        result[period+'_snapshot_at']=frame.attrs.get('fetched_at')
                    else:
                        raw, complete = self.history(symbol, kind, days, sess)
                        result[period] = normalize(raw, 'DAY' if period == 'daily' else '1M', now_et())
                        result[period].attrs['fetched_at']=now_et().isoformat()
                        result[period+'_snapshot_at']=result[period].attrs['fetched_at']
                        if not result[period].empty:self.history_cache[cache_key]=(time.monotonic(),result[period].copy(deep=True),complete)
                    result[f'{period}_pagination_complete'] = complete
                    if not complete:
                        result['errors'].append(f'{period}: 分页上限，范围不完整')
                except Exception as exc:
                    logging.getLogger('ict.stability').exception('历史周期读取失败 symbol=%s period=%s',symbol,period)
                    result['errors'].append(f'{period}: {type(exc).__name__}；无可验证行情')
        except Exception as exc:
            self.connect_failures+=1
            result['opend_status']='UNAVAILABLE'
            self.next_connect=time.monotonic()+min(30,2**self.connect_failures)
            logging.getLogger('ict.stability').exception('行情连接或查询失败 symbol=%s',symbol)
            result['health']['reason'] = f'{type(exc).__name__}：OpenD 不可用或时间/数据检查失败'
            self.close()
        return result

    def history(self, symbol, kind, days, sess):
        import futu as ft
        end = now_et().date()
        frames, key = [], None
        began=time.monotonic()
        for _ in range(15):
            if time.monotonic()-began>20:raise TimeoutError('历史分页总预算耗尽')
            ret, raw, key = self.ctx.request_history_kline(
                symbol, start=str(end-timedelta(days=days)), end=str(end), ktype=kind,
                autype=ft.AuType.NONE, max_count=1000, page_req_key=key, session=sess)
            if ret != ft.RET_OK:
                raise RuntimeError('历史数据权限/配额/API 错误')
            frames.append(raw)
            if key is None:
                return pd.concat(frames, ignore_index=True), True
        return pd.concat(frames, ignore_index=True), False
