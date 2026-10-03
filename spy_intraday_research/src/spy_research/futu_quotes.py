"""Quote-only boundary: no trade context, subscription or order side effects."""
import os
import time
import random
import pandas as pd
from futu import OpenQuoteContext, RET_OK, KLType, AuType

class QuoteReader:
    def __init__(self, interval=3.1, retries=5):
        self.interval, self.retries, self.last = interval, retries, 0
        self.ctx = OpenQuoteContext(host=os.getenv('FUTU_HOST','127.0.0.1'),
                                    port=int(os.getenv('FUTU_PORT','11111')))

    def close(self): self.ctx.close()

    def history(self, start, end, kind):
        token, seen, pages, row_keys = None, set(), [], set()
        while True:
            for attempt in range(self.retries):
                time.sleep(max(0, self.interval - (time.monotonic()-self.last)))
                ret, data, next_token = self.ctx.request_history_kline(
                    'US.SPY', start=start, end=end, ktype=getattr(KLType,kind),
                    autype=AuType.NONE, max_count=1000, page_req_key=token, extended_time=False)
                self.last = time.monotonic()
                if ret == RET_OK: break
                # Do not emit broker response objects containing personal information.
                if not any(term in str(data).lower() for term in ['timeout','frequency','频率','超时']):
                    raise RuntimeError('HISTORY_REQUEST_REJECTED: check permissions/quota')
                if attempt + 1 == self.retries: raise RuntimeError('HISTORY_RETRY_EXHAUSTED')
                time.sleep(min(30, 2**attempt) + random.random())
            current_keys = set(data.time_key) if not data.empty else set()
            if next_token is not None and (next_token in seen or not (current_keys-row_keys)):
                raise RuntimeError('PAGINATION_NO_PROGRESS')
            row_keys.update(current_keys)
            pages.append(data)
            if next_token is None: break
            seen.add(next_token)
            token = next_token
        return pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()
