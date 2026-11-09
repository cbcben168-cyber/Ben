"""One-off, quote-only native 60M capture into a new versioned directory.

Stores QFQ/NONE 60M, same-batch DAY/rehab, per-page metadata and raw SHA256.
Never subscribes, schedules, publishes a pointer or writes existing archives.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import logging.handlers
from pathlib import Path
import sys
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desk.clock import ET
from desk.futu_hourly import verify_hourly
from capture_futu_daily import SYMBOLS


def now():
    return datetime.now(timezone.utc).isoformat()


def capture(output, start, end, symbols):
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(format='FUTU_HOURLY_CAPTURE_V1', start=start, end=end, symbols={})
    with patch.object(logging.handlers, 'TimedRotatingFileHandler', lambda *a, **kw: logging.NullHandler()):
        import futu as ft
        ft.SysConfig.set_all_thread_daemon(True)
        ft.SysConfig.enable_console_log(False)
        ctx = ft.OpenQuoteContext(host='127.0.0.1', port=11111, is_async_connect=True)
        ctx.set_sync_query_connect_timeout(5)
        try:
            ret, user = ctx.get_user_info()
            manifest['permission'] = dict(ret=ret, us_qot_right=user.get('us_qot_right', 'UNKNOWN'))
            ret, quota = ctx.get_history_kl_quota(get_detail=True)
            if ret != ft.RET_OK:
                raise RuntimeError('历史额度无法核验')
            used, remaining, detail = quota
            existing = {r['code'] for r in detail}
            needed = sum('US.'+s not in existing for s in symbols)
            manifest['quota'] = dict(used=used, remaining=remaining, new_symbols_needed=needed,
                                     existing_symbols=sorted(existing))
            if remaining < needed:
                raise RuntimeError('历史额度不足；不发起历史请求')

            def series(symbol, kind, adjustment, first=start, last=end):
                request = dict(symbol=symbol, start=first, end=last, ktype=kind, session='RTH',
                               autype=adjustment, requested_at_utc=now())
                records, pages, key, seen = [], [], None, set()
                for _ in range(30):
                    ret, frame, next_key = ctx.request_history_kline(symbol, start=first, end=last,
                        ktype=getattr(ft.KLType, kind), session=ft.Session.RTH,
                        autype=getattr(ft.AuType, adjustment), max_count=250, page_req_key=key)
                    if ret != ft.RET_OK or frame.empty:
                        raise RuntimeError(f'{symbol}/{kind}/{adjustment}: ret={ret}, {str(frame)[:220]}')
                    records.extend(json.loads(frame.to_json(orient='records', double_precision=15)))
                    pages.append(dict(rows=len(frame), ret=ret, has_next=bool(next_key), acquired_at_utc=now()))
                    time.sleep(.6)
                    if not next_key:
                        return dict(request=request, acquired_at_utc=now(), records=records,
                                    page_complete=True, pages=pages)
                    if next_key in seen:
                        raise RuntimeError('重复分页游标')
                    key = next_key
                    seen.add(key)
                raise RuntimeError('分页预算耗尽')

            for ticker in symbols:
                symbol = 'US.'+ticker
                payload = dict(format='FUTU_HOURLY_V1', symbol=symbol, sdk_version=ft.__version__,
                               valuation_date=datetime.now(ET).date().isoformat(), responses={})
                status = {}
                try:
                    for adj in ('QFQ', 'NONE'):
                        payload['responses'][adj] = series(symbol, 'K_60M', adj)
                    daily = dict(format='FUTU_DAILY_V1', provider='FUTU_OPEND', symbol=symbol,
                                 valuation_date=payload['valuation_date'], responses={})
                    for adj in ('QFQ', 'NONE'):
                        daily['responses'][adj] = series(symbol, 'K_DAY', adj)
                    requested = now()
                    ret, rehab = ctx.get_rehab(symbol)
                    if ret != ft.RET_OK:
                        raise RuntimeError('复权事件不可用')
                    daily['rehab'] = dict(request=dict(symbol=symbol, method='get_rehab', requested_at_utc=requested),
                        acquired_at_utc=now(), records=json.loads(rehab.to_json(orient='records', double_precision=15)))
                    payload['daily_companion'] = daily
                    meta, _ = verify_hourly(payload)
                    status = dict(status='PASS', verification=meta)
                except Exception as exc:
                    status = dict(status='UNAVAILABLE', reason=str(exc))
                blob = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
                (output/(ticker+'.json')).write_bytes(blob)
                manifest['symbols'][symbol] = dict(status, sha256=hashlib.sha256(blob).hexdigest())
                (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
                print(symbol, status.get('status'), status.get('reason', status.get('verification',{}).get('bars')), flush=True)
            # Independent raw 1M probes for regular and early-close boundaries.
            for day in ('2025-11-28', '2026-11-06'):
                for kind in ('K_1M', 'K_60M'):
                    probe = series('US.SMH', kind, 'QFQ', day, day)
                    blob = json.dumps(probe, ensure_ascii=False, indent=2).encode('utf-8')
                    name = 'SMH-'+kind+'-'+day+'.json'
                    (output/name).write_bytes(blob)
                    manifest.setdefault('boundary_probes', {})[name] = hashlib.sha256(blob).hexdigest()
        finally:
            ctx.close()
            (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', default='2026-07-02')
    parser.add_argument('--end', default='2026-11-06')
    parser.add_argument('--symbols', nargs='+', default=SYMBOLS)
    args = parser.parse_args()
    capture(args.output, args.start, args.end, args.symbols)
