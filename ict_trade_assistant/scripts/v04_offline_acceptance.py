"""已有真实历史前缀与原库只读指纹验收，不连接行情。"""
from pathlib import Path
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import timedelta
from collections import Counter
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desk.ict_v03 import scan
from desk.decision import decision
from desk.observations import build_observation, SYMBOLS
from desk.store import DEFAULTS
from desk.clock import bounds


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original',type=Path,required=True)
    args=parser.parse_args()
    out=ROOT/'data/v04_acceptance';out.mkdir(parents=True,exist_ok=True)
    source=args.original/'data/v02_acceptance/real_snapshots.json'
    saved=json.loads(source.read_text(encoding='utf-8'))
    result=dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        boundary='既有真实历史；不证明供应商实时最终性、历史PIT或真实RTH；合格真实MSS完整链仍为零',symbols={})
    for symbol in SYMBOLS:
        data=saved[symbol]
        for period in ('minute','daily'):
            data[period]=pd.DataFrame(data[period])
            data[period]['ts']=pd.to_datetime(data[period].ts,utc=True).dt.tz_convert('America/New_York')
        frame=data['minute'];day=frame[frame.session=='RTH'].ts.max().date();start,end=bounds(day)
        checks=[]
        for minutes in [59,61,62,121,122,181,182,241,242,301,302,389,391,392]:
            now=start+timedelta(minutes=minutes)
            report=scan(symbol,frame,now)
            prefix=scan(symbol,frame[frame.ts<now],now)
            o=build_observation(symbol,data,DEFAULTS,now)
            prefix_data=dict(data,minute=frame[frame.ts<now],daily=data['daily'][data['daily'].ts<now])
            prefix_o=build_observation(symbol,prefix_data,DEFAULTS,now)
            assert report==prefix
            assert decision(symbol,o,report,now)==decision(symbol,prefix_o,prefix,now)
            checks.append(now.isoformat())
        final=scan(symbol,frame,end+timedelta(minutes=2))
        o=build_observation(symbol,data,DEFAULTS,end+timedelta(minutes=2))
        result['symbols'][symbol]=dict(prefix_checks=checks,events=dict(Counter(e['kind'] for e in final['events'])),
            independent_fvg=sum(not z['setup_id'] for z in final['fvgs']),decision=decision(symbol,o,final,end+timedelta(minutes=2)))
    baseline=json.loads((out/'baseline.json').read_text(encoding='utf-8'))
    unchanged={name:hashlib.sha256((args.original/name).read_bytes()).hexdigest()==digest for name,digest in baseline['files'].items()}
    assert all(unchanged.values())
    assert all(hashlib.sha256((args.original/name).read_bytes()).hexdigest()==digest for name,digest in baseline['untracked'].items())
    with sqlite3.connect((args.original/'data/desk.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
        current={t:hashlib.sha256(json.dumps(c.execute(f'SELECT * FROM {t} ORDER BY rowid').fetchall(),ensure_ascii=False).encode()).hexdigest() for t in baseline['tables']}
        result['database_integrity']=c.execute('PRAGMA integrity_check').fetchone()[0]
    result['original_tables_unchanged']={t:current[t]==v for t,v in baseline['tables'].items()}
    result['original_source_unchanged']=unchanged
    assert all(result['original_tables_unchanged'].values())
    result['frozen_content_unchanged']={name:(ROOT/name).read_text(encoding='utf-8')==(args.original/name).read_text(encoding='utf-8') for name in ['desk/ict_v03.py','LIVE_RTH_ACCEPTANCE_CHECKLIST.md']}
    assert all(result['frozen_content_unchanged'].values())
    (out/'offline-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(symbols=len(result['symbols']),prefix_checks=sum(len(x['prefix_checks']) for x in result['symbols'].values()),original_tables_unchanged=result['original_tables_unchanged']),ensure_ascii=False))


if __name__=='__main__':main()
