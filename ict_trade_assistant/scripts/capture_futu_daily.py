"""One-off quote-only capture. No subscription, scheduler, or trading context."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import logging
import logging.handlers
from pathlib import Path
import time
from unittest.mock import patch

SYMBOLS = ('SPY', 'QQQ', 'IWM', 'SOXX', 'SMH', 'VOO', 'IVV', 'VTI', 'VEA', 'VUG',
           'IEFA', 'VTV', 'SPYM', 'BND', 'VXUS', 'IEMG', 'VGT', 'GLD', 'AGG', 'IWF',
           'IJH', 'VWO', 'XLK')


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def capture(output):
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
            for ticker in SYMBOLS:
                symbol = 'US.' + ticker
                payload = dict(format='FUTU_DAILY_V1', provider='FUTU_OPEND', symbol=symbol,
                               sdk_version=futu.__version__, responses={})
                for adjustment in ('QFQ', 'NONE'):
                    request = dict(symbol=symbol, start='2026-07-02', end='2026-11-06',
                                   ktype='K_DAY', session='RTH', autype=adjustment,
                                   requested_at_utc=utc_now())
                    ret, frame, page = quote.request_history_kline(
                        symbol, start=request['start'], end=request['end'], ktype=KLType.K_DAY,
                        session=Session.RTH, autype=getattr(AuType, adjustment), max_count=1000)
                    if ret != RET_OK or page or len(frame) != 90:
                        raise RuntimeError(f'{symbol}/{adjustment}: incomplete history; ret={ret}')
                    payload['responses'][adjustment] = dict(request=request, acquired_at_utc=utc_now(),
                        page_complete=True, records=json.loads(frame.to_json(orient='records', double_precision=15)))
                    time.sleep(1.15)
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
                print(symbol + ' QFQ=90 NONE=90 rehab=' + str(len(actions)), flush=True)
        finally:
            quote.close()
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    capture(parser.parse_args().output)
