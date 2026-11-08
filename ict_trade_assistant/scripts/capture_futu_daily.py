"""One-off quote-only capture. No subscription, scheduler, or trading context."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import logging.handlers
import os
from pathlib import Path
import time
from unittest.mock import patch

SYMBOLS = ('SPY', 'QQQ', 'IWM', 'SOXX', 'SMH', 'VOO', 'IVV', 'VTI', 'VEA', 'VUG',
           'IEFA', 'VTV', 'SPYM', 'BND', 'VXUS', 'IEMG', 'VGT', 'GLD', 'AGG', 'IWF',
           'IJH', 'VWO', 'XLK')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def capture(output, start='2026-07-02', end='2026-11-06', symbols=SYMBOLS, progress=None):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    manifest = dict(format='FUTU_DAILY_CAPTURE_V1', files={})
    # Futu otherwise opens a file logger on SDK import. All evidence goes only
    # to the explicitly requested, new isolated output directory.
    with patch.object(logging.handlers, 'TimedRotatingFileHandler',
                      lambda *args, **kwargs: logging.NullHandler()):
        import futu
        from futu import OpenQuoteContext, SysConfig, KLType, Session, AuType, RET_OK
        SysConfig.set_all_thread_daemon(True)
        SysConfig.enable_console_log(False)
        quote = OpenQuoteContext(host='127.0.0.1', port=11111)
        try:
            for index, ticker in enumerate(symbols, 1):
                symbol = 'US.' + ticker
                payload = dict(format='FUTU_DAILY_V1', provider='FUTU_OPEND', symbol=symbol,
                               sdk_version=futu.__version__, responses={})
                for adjustment in ('QFQ', 'NONE'):
                    request = dict(symbol=symbol, start=start, end=end,
                                   ktype='K_DAY', session='RTH', autype=adjustment,
                                   requested_at_utc=utc_now())
                    records, page, seen_pages, pages = [], None, set(), []
                    while True:
                        ret, frame, next_page = quote.request_history_kline(
                            symbol, start=request['start'], end=request['end'], ktype=KLType.K_DAY,
                            session=Session.RTH, autype=getattr(AuType, adjustment),
                            max_count=50, page_req_key=page)
                        if ret != RET_OK or frame.empty:
                            raise RuntimeError(f'{symbol}/{adjustment}: incomplete history; ret={ret}')
                        records.extend(json.loads(frame.to_json(orient='records', double_precision=15)))
                        pages.append(dict(ret=ret, rows=len(frame), has_next=bool(next_page), acquired_at_utc=utc_now()))
                        time.sleep(1.15)
                        if not next_page:
                            break
                        if next_page in seen_pages:
                            raise RuntimeError(f'{symbol}/{adjustment}: repeated Futu page')
                        seen_pages.add(next_page)
                        page = next_page
                    payload['responses'][adjustment] = dict(request=request, acquired_at_utc=utc_now(),
                        page_complete=True, records=records, pages=pages)
                requested = utc_now()
                ret, actions = quote.get_rehab(symbol)
                if ret != RET_OK:
                    raise RuntimeError(f'{symbol}: rehabilitation request failed; ret={ret}')
                payload['rehab'] = dict(request=dict(symbol=symbol, method='get_rehab', requested_at_utc=requested),
                    acquired_at_utc=utc_now(), records=json.loads(actions.to_json(orient='records', double_precision=15)))
                payload['valuation_date'] = datetime.now().astimezone(
                    __import__('zoneinfo').ZoneInfo('America/New_York')).date().isoformat()
                path = output / (ticker + '.json')
                content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
                with path.open('xb') as stream:
                    stream.write(content)
                manifest['files'][path.name] = hashlib.sha256(content).hexdigest()
                if progress:
                    progress(index, symbol)
                print(symbol + ' QFQ=' + str(len(payload['responses']['QFQ']['records']))
                      + ' NONE=' + str(len(payload['responses']['NONE']['records']))
                      + ' rehab=' + str(len(actions)), flush=True)
        finally:
            quote.close()
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', default='2026-07-02')
    parser.add_argument('--end', default='2026-11-06')
    parser.add_argument('--progress', type=Path)
    args = parser.parse_args()
    def report(count, symbol):
        if args.progress:
            temp = args.progress.with_suffix('.tmp')
            temp.write_text(json.dumps(dict(phase='获取并核查Futu日K', completed=count,
                                            symbol=symbol), ensure_ascii=False), encoding='utf-8')
            os.replace(temp, args.progress)
    capture(args.output, args.start, args.end, progress=report)
