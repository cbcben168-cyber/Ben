"""Bounded daily updater; only the local market-data client may perform HTTP GETs."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
import pandas as pd
from .clock import CAL, ET, bounds
from .history_import import DailyArchive, validate_daily


def latest_completed(now):
    now=pd.Timestamp(now).tz_convert(ET)
    day=CAL.date_to_session(pd.Timestamp(now.date()),direction='previous').date()
    if now.to_pydatetime()<bounds(day)[1]+timedelta(minutes=2):
        day=CAL.previous_session(pd.Timestamp(day)).date()
    return str(day)


def provider_ready(day, now):
    # Supplier day/RTH equivalence is unverified. Never save an open NY calendar day.
    ready=pd.Timestamp(day,tz=ET)+pd.DateOffset(days=1)+pd.Timedelta(minutes=15)
    return pd.Timestamp(now)>=ready


class DataError(Exception):
    pass


class LocalAlpaca:
    def __init__(self):
        self.key=os.environ.get('APCA_API_KEY_ID','')
        self.secret=os.environ.get('APCA_API_SECRET_KEY','')

    def preflight(self):
        return dict(configured=bool(self.key and self.secret),
                    status='LOCAL_CREDENTIALS_UNVERIFIED' if self.key and self.secret else 'BLOCKED_NO_LOCAL_CREDENTIALS',
                    sip_permission='NOT_VERIFIED',rate_limit='UNKNOWN',unattended_proven=False)

    def fetch(self, symbol, start, end):
        if not self.key or not self.secret:raise DataError('BLOCKED_NO_LOCAL_CREDENTIALS')
        request=dict(symbols=[symbol[3:]],timeframe='1Day',feed='sip',adjustment='raw',start=start,end=end)
        params=dict(symbols=symbol[3:],timeframe='1Day',feed='sip',adjustment='raw',start=start,end=end,limit=1000,sort='asc')
        url='https://data.alpaca.markets/v2/stocks/bars?'+urllib.parse.urlencode(params)
        req=urllib.request.Request(url,headers={'APCA-API-KEY-ID':self.key,'APCA-API-SECRET-KEY':self.secret})
        try:
            with urllib.request.urlopen(req,timeout=15) as response:
                data=json.loads(response.read(2_000_000))
                limit=response.headers.get('X-RateLimit-Limit','')
        except urllib.error.HTTPError as exc:
            # Do not log response bodies, request headers, credentials or arbitrary exceptions.
            raise DataError('PROVIDER_HTTP_'+str(exc.code)) from None
        except Exception:
            raise DataError('PROVIDER_NETWORK_OR_RESPONSE_ERROR') from None
        if data.get('next_page_token'):raise DataError('PAGINATION_REQUIRED_REQUEST_TOO_LARGE')
        bars=[]
        for r in data.get('bars',{}).get(symbol[3:],[]):
            bars.append(dict(symbol=symbol[3:],timestamp=r['t'],open=r['o'],high=r['h'],low=r['l'],close=r['c'],volume=r['v']))
        return dict(tool='get_stock_bars',request=request,bars={symbol[3:]:bars},native_response=data,
                    reported_rate_limit=int(limit) if limit.isdigit() else 'UNKNOWN')


def probe_local(root, client=None, now=None):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    client=client or LocalAlpaca();now=now or datetime.now(timezone.utc)
    report=dict(client.preflight(),checked_at=pd.Timestamp(now).isoformat())
    if report['configured']:
        day=latest_completed(now)
        if not provider_ready(day,now):day=str(CAL.previous_session(pd.Timestamp(day)).date())
        try:
            start=pd.Timestamp(day,tz=ET).isoformat()
            end=(pd.Timestamp(day,tz=ET)+pd.DateOffset(days=1)).isoformat()
            payload=client.fetch('US.SPY',start,end)
            validate_daily(payload,'US.SPY',datetime.now(timezone.utc).isoformat())
            report.update(status='PASS',sip_permission='REQUEST_SUCCEEDED',rate_limit=payload.get('reported_rate_limit','UNKNOWN'))
        except (DataError,ValueError,KeyError,TypeError):
            report.update(status='BLOCKED_LOCAL_SIP_VALIDATION',sip_permission='NOT_VERIFIED')
    (root/'access.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    return report


def archive_dates(archive, symbol):
    saved=archive.read(symbol)
    return {str(x.date()) for x in saved[1].ts} if saved else set()


def make_plan(entries, legacy, base, updates, now):
    target=latest_completed(now);rows=[]
    for entry in entries:
        if not entry['enabled']:continue
        c=entry['symbol']
        original={r['ts'][:10] for r in legacy.get(c,{}).get('daily',[])} or archive_dates(base,c)
        changed=archive_dates(updates,c)
        start=min(original|changed) if original or changed else target
        expected=[str(x.date()) for x in CAL.sessions_in_range(start,target)]
        missing=[d for d in expected if d not in original|changed]
        rows.append(dict(symbol=c,target=target,baseline_last=max(original) if original else None,
                         update_last=max(changed) if changed else None,last=max(original|changed) if original or changed else None,
                         missing=missing,status='UP_TO_DATE' if not missing else 'MISSING',reason=''))
    return rows


def missing_ranges(missing):
    groups=[]
    for day in missing:
        if groups and str(CAL.next_session(pd.Timestamp(groups[-1][-1])).date())==day:groups[-1].append(day)
        else:groups.append([day])
    return groups


@contextmanager
def run_lock(root):
    root.mkdir(parents=True,exist_ok=True)
    f=(root/'update.lock').open('a+b')
    if not f.tell():f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        f.close();raise DataError('RUN_ALREADY_ACTIVE') from None
    try:yield
    finally:
        f.seek(0)
        if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)
        f.close()


def save_result(root, result):
    text=json.dumps(result,ensure_ascii=False,indent=2)
    temp=root/'latest.tmp';temp.write_text(text,encoding='utf8');temp.replace(root/'latest.json')
    with (root/'runs.jsonl').open('a',encoding='utf8') as f:f.write(json.dumps(result,ensure_ascii=False)+'\n')


def run_update(root, entries, legacy, base, client=None, now=None, sleep=time.sleep, interval=6):
    root=Path(root);now=now or datetime.now(timezone.utc);client=client or LocalAlpaca()
    try:
        with run_lock(root):
            updates=DailyArchive(root/'updates.sqlite3')
            rows=make_plan(entries,legacy,base,updates,now)
            preflight=client.preflight()
            result=dict(started_at=pd.Timestamp(now).isoformat(),target=latest_completed(now),status='RUNNING',
                        local_access=preflight,rows=rows,requests=0,added=0,scheduler='NOT_REGISTERED',unattended_proven=False)
            began=time.monotonic()
            for row in rows:
                if not row['missing']:continue
                if not preflight['configured']:
                    row.update(status='BLOCKED',reason='NO_AUTHORIZED_LOCAL_DATA_ACCESS');continue
                for group in missing_ranges(row['missing']):
                    if time.monotonic()-began>900:
                        row.update(status='BLOCKED',reason='RUN_TIME_BUDGET_EXCEEDED');break
                    ready=[d for d in group if provider_ready(d,now)]
                    if not ready:
                        row.update(status='PENDING_PROVIDER_DATA',reason='NY供应商日尚未结束；未保存形成中日K');continue
                    if len(ready)>500:
                        row.update(status='BLOCKED',reason='HISTORY_GAP_TOO_LARGE_FOR_BOUNDED_RUN');break
                    start=pd.Timestamp(ready[0],tz=ET).isoformat()
                    end=(pd.Timestamp(ready[-1],tz=ET)+pd.DateOffset(days=1)).isoformat()
                    for attempt in range(3):
                        if result['requests']:sleep(interval)
                        result['requests']+=1
                        try:
                            payload=client.fetch(row['symbol'],start,end)
                            bars=payload.get('bars',{}).get(row['symbol'][3:],[])
                            if not bars:raise DataError('PENDING_PROVIDER_DATA')
                            imported=updates.import_payload(payload,row['symbol'],datetime.now(timezone.utc).isoformat())
                            result['added']+=imported['added']
                            row.update(status='UPDATED',reason='')
                            result['local_access'].update(sip_permission='REQUEST_SUCCEEDED',unattended_proven=False)
                            break
                        except DataError as exc:
                            row.update(status='PENDING_PROVIDER_DATA' if str(exc)=='PENDING_PROVIDER_DATA' else 'FAILED',reason=str(exc))
                            if str(exc) in ('PROVIDER_HTTP_401','PROVIDER_HTTP_403'):break
                        except (ValueError,KeyError,TypeError):
                            row.update(status='FAILED',reason='IMPORT_VALIDATION_OR_CONFLICT_REJECTED');break
                        if attempt<2:sleep(2*(attempt+1))
            refreshed={r['symbol']:r for r in make_plan(entries,legacy,base,updates,now)}
            for row in rows:
                row.update({k:refreshed[row['symbol']][k] for k in ('last','update_last','missing')})
                if row['status']=='UPDATED' and row['missing']:row.update(status='PENDING_PROVIDER_DATA',reason='供应商响应仍缺完整交易日')
            result['status']='COMPLETE' if all(not r['missing'] for r in rows) else 'BLOCKED' if not preflight['configured'] else 'PARTIAL'
            result['completed_at']=datetime.now(timezone.utc).isoformat()
            save_result(root,result)
            return result
    except DataError as exc:
        return dict(status='BLOCKED',reason=str(exc),unattended_proven=False)
