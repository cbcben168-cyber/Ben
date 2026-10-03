"""Immutable cached inputs and bounded monthly collection."""
from pathlib import Path
import hashlib
import json
import time
from datetime import datetime, timezone
import pandas as pd
from .data import schedule, normalize, quality, aggregate5_fast

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def atomic(path, text):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(text,encoding='utf-8'); temporary.replace(path)

def write_csv(path, frame): atomic(path,frame.to_csv(index=False,lineterminator='\n'))
def write_json(path, data): atomic(path,json.dumps(data,indent=2,default=str,allow_nan=False))

def record(path, frame, **metadata):
    write_csv(path,frame)
    write_json(path.with_suffix('.json'),dict(sha256=digest(path),fetched_at_utc=datetime.now(timezone.utc).isoformat(),
                                           symbol='US.SPY',adjustment='NONE',vendor='Futu',**metadata))

def read(path):
    path = Path(path)
    marker=path.with_suffix('.json')
    if not marker.exists() or json.loads(marker.read_text())['sha256']!=digest(path):
        raise ValueError('RAW_HASH_MISMATCH')
    return pd.read_csv(path)

def collect(root, start, end, interval=1.1):
    """New contract: 1m is canonical; native cross-frequency volumes stay diagnostic."""
    from .futu_quotes import QuoteReader
    reader=QuoteReader(interval=interval)
    try:
        for month in pd.period_range(start,end,freq='M'):
            left=max(start,month.start_time.strftime('%Y-%m-%d'))
            right=min(end,month.end_time.strftime('%Y-%m-%d'))
            sessions=[x.strftime('%Y-%m-%d') for x in schedule(left,right).index]
            for kind in ['K_1M','K_DAY']:
                paths=[root/'data/raw'/kind/(date+'.csv') for date in sessions]
                if paths and all(p.exists() and p.with_suffix('.json').exists() for p in paths):
                    for p in paths: read(p)
                    continue
                frame=reader.history(left,right,kind)
                if frame.empty: raise ValueError('EMPTY_HISTORY')
                dates=pd.to_datetime(frame.time_key).dt.strftime('%Y-%m-%d')
                for date,path in zip(sessions,paths):
                    if path.exists() and path.with_suffix('.json').exists(): read(path); continue
                    record(path,frame[dates==date],kind=kind,session_date=date)
            # One native-5m sample per month; never use it to replace canonical bars.
            if sessions:
                path=root/'data/raw/K_5M'/(sessions[0]+'.csv')
                if path.exists(): read(path)
                else: record(path,reader.history(sessions[0],sessions[0],'K_5M'),kind='K_5M')
            print(json.dumps(dict(stage='COLLECT',month=str(month),sessions=len(sessions))),flush=True)
        path=root/'data/raw/corporate_actions.csv'
        if not path.exists():
            ret,frame=reader.ctx.get_rehab('US.SPY')
            if ret != 0: raise ValueError('CORPORATE_ACTIONS_UNAVAILABLE')
            record(path,frame,kind='REHAB')
    finally: reader.close()

def prepare(root,start,end):
    frames=[]
    for day in schedule(start,end).index:
        frame=read(root/'data/raw/K_1M'/(day.strftime('%Y-%m-%d')+'.csv'))
        if not frame.empty: frames.append(frame)
    if not frames: raise ValueError('EMPTY_HISTORY')
    minute=normalize(pd.concat(frames,ignore_index=True),'end')
    good,report=quality(minute,start,end)
    folder=root/'data/normalized'; folder.mkdir(parents=True,exist_ok=True)
    write_csv(folder/'quality.csv',report)
    write_csv(root/'data/quarantine/bars.csv',minute[~minute.session_date.isin(good.session_date)])
    write_csv(folder/'bars_1m.csv',good)
    five=aggregate5_fast(good)
    write_csv(folder/'bars_5m.csv',five)
    comparisons=[]
    for path in sorted((root/'data/raw/K_5M').glob('*.csv')):
        raw=read(path)
        if raw.empty: continue
        native=normalize(raw,'end',5)
        sample=five[five.session_date.isin(native.session_date)]
        joined=sample.merge(native,on=['code','ts_start_utc'],how='outer',suffixes=('_1m','_native'),indicator=True)
        for col in ['open','high','low','close','volume','turnover']:
            if col+'_native' in joined: joined[col+'_diff']=joined[col+'_1m']-joined[col+'_native']
        comparisons.append(joined)
    cross=pd.concat(comparisons,ignore_index=True) if comparisons else pd.DataFrame()
    write_csv(folder/'cross_frequency_diagnostic.csv',cross)
    fraction=float((report.status!='PASS').mean())
    manifest=dict(start=start,end=end,qualified_sessions=int((report.status=='PASS').sum()),
                  excluded_fraction=fraction,canonical='Futu unadjusted RTH 1m; daily and 5m derived from same bars',
                  volume_cross_frequency_qualified=False,formal_data_gate=False,
                  reason='CROSS_FREQUENCY_VOLUME_UNEXPLAINED',
                  diagnostic_gate=bool(not good.empty and fraction<=0.01),
                  files={p.name:digest(p) for p in folder.glob('*.csv')},
                  corporate_actions_sha256=digest(root/'data/raw/corporate_actions.csv') if (root/'data/raw/corporate_actions.csv').exists() else None)
    write_json(folder/'manifest.json',manifest)
    return manifest

def normalized(root):
    folder=root/'data/normalized'
    manifest=json.loads((folder/'manifest.json').read_text())
    if not manifest['diagnostic_gate']: raise ValueError('CANONICAL_DATA_GATE_FAILED')
    for name,expected in manifest['files'].items():
        if digest(folder/name)!=expected: raise ValueError('NORMALIZED_HASH_MISMATCH')
    minute=pd.read_csv(folder/'bars_1m.csv',parse_dates=['ts_start_utc','ts_end_utc'])
    five=pd.read_csv(folder/'bars_5m.csv',parse_dates=['ts_start_utc','ts_end_utc'])
    return minute,five,manifest
