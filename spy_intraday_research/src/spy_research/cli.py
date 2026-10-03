"""Phase 1 CLI; cached analysis never initializes OpenD."""
import argparse
import hashlib
import importlib.metadata as meta
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from .data import normalize, quality, aggregate5, schedule

ROOT = Path(__file__).resolve().parents[2]

def atomic(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)

def csv(path, frame): atomic(path, frame.to_csv(index=False, lineterminator='\n'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def ingest(args, config):
    from .futu_quotes import QuoteReader
    reader = QuoteReader(config['request_interval_seconds'], config['max_retries'])
    try:
        for kind in ['K_1M','K_5M','K_DAY']:
            for date in pd.date_range(args.start, args.end):
                day = date.strftime('%Y-%m-%d')
                path = ROOT/'data/raw'/kind/(day+'.csv')
                marker = path.with_suffix('.json')
                if path.exists() and marker.exists():
                    if json.loads(marker.read_text())['sha256'] != sha(path):
                        raise ValueError('RAW_HASH_MISMATCH')
                    continue
                frame = reader.history(day, day, kind)
                csv(path, frame)
                atomic(marker, json.dumps(dict(sha256=sha(path), symbol='US.SPY',
                    adjustment='NONE', vendor='Futu', kind=kind,
                    fetched_at=datetime.now(timezone.utc).isoformat()), indent=2))
    finally: reader.close()

def load(kind, start, end):
    chunks = []
    for date in pd.date_range(start, end):
        path = ROOT/'data/raw'/kind/(date.strftime('%Y-%m-%d')+'.csv')
        marker = path.with_suffix('.json')
        if not path.exists() or not marker.exists(): raise ValueError('MISSING_RAW_PARTITION')
        if sha(path) != json.loads(marker.read_text())['sha256']: raise ValueError('RAW_HASH_MISMATCH')
        frame = pd.read_csv(path)
        if not frame.empty: chunks.append(frame)
    if not chunks: raise ValueError('EMPTY_HISTORY')
    return pd.concat(chunks, ignore_index=True)

def validate(args, output, config):
    raw = load('K_1M',args.start,args.end)
    normalized = normalize(raw, config['timestamp_semantics'])
    good, report = quality(normalized,args.start,args.end)
    csv(output/'data_quality.csv',report)
    csv(output/'quarantine.csv',normalized[~normalized.session_date.isin(good.session_date)])
    csv(output/'bars_1m.csv',good)
    five = aggregate5(good)
    csv(output/'bars_5m.csv',five)
    native = normalize(load('K_5M',args.start,args.end), config['timestamp_semantics'], minutes=5)
    compare = five.merge(native, on=['code','ts_start_utc'], how='outer', suffixes=('_derived','_native'), indicator=True)
    for col in ['open','high','low','close','volume']:
        compare[col+'_diff'] = compare[col+'_derived']-compare[col+'_native']
    compare['match'] = (compare['_merge'] == 'both') & (compare[[c+'_diff' for c in ['open','high','low','close']]].abs() <= 0.0001).all(axis=1) & (compare.volume_diff == 0)
    csv(output/'native_5m_comparison.csv',compare)
    daily = load('K_DAY',args.start,args.end)
    daily['session_date'] = pd.to_datetime(daily.time_key).dt.strftime('%Y-%m-%d')
    derived = good.groupby('session_date').agg(open=('open','first'), high=('high','max'),low=('low','min'),close=('close','last'),volume=('volume','sum')).reset_index()
    daily_compare = derived.merge(daily,on='session_date',how='outer',suffixes=('_rth','_vendor'),indicator=True)
    csv(output/'daily_comparison.csv',daily_compare)
    fraction = (report.status != 'PASS').mean()
    mismatches = int((~compare.match).sum())
    atomic(output/'data_quality.md', f'# Data quality\n\nSessions: {len(report)}\n\nQuarantine fraction: {fraction:.4%}\n\nNative 5m mismatches: {mismatches}\n\nDaily comparison is diagnostic pending vendor session qualification.\n\nTimestamp contract: ET bar-{config["timestamp_semantics"]}; qualified against RTH boundaries and native aggregation.\n')
    if good.empty or fraction > config['exclude_fraction_limit'] or mismatches:
        raise ValueError('FAILED_DATA_GATE')

def doctor(args, output):
    from .futu_quotes import QuoteReader
    reader = QuoteReader()
    try:
        ret, state = reader.ctx.get_global_state()
        if ret != 0: raise RuntimeError('OPEND_UNAVAILABLE')
        # Allowlist only non-personal service diagnostics.
        safe = {k:state.get(k) for k in ['qot_logined','server_ver','market_us','timestamp']}
        rows = {}
        for kind in ['K_1M','K_5M','K_DAY']:
            frame = reader.history(args.start,args.end,kind)
            rows[kind] = dict(rows=len(frame), first=str(frame.time_key.min()) if not frame.empty else None,
                              last=str(frame.time_key.max()) if not frame.empty else None)
        payload = dict(service=safe, history=rows, sdk=meta.version('futu-api'),
                       realtime_permission='NOT_QUALIFIED', earliest_available_history='NOT_QUALIFIED',
                       timestamp_semantics='ET end observed: 1m 09:31-16:00 and 5m 09:35-16:00; validate aggregation',
                       status='READ_ONLY_HISTORY_SMOKE_ONLY')
        atomic(output/'capability_report.json',json.dumps(payload,indent=2,default=str))
        atomic(output/'capability_report.md','# Capability report\n\n```json\n'+json.dumps(payload,indent=2,default=str)+'\n```\n')
    finally: reader.close()

def main():
    if len(sys.argv)>1 and sys.argv[1] in ['collect','prepare','register','study','evaluate','lock','freeze-diagnostic','paper','daily-review','replay']:
        from .workflow import main as workflow
        return workflow(sys.argv[1:])
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['doctor','ingest','validate-data'])
    parser.add_argument('--config',default=str(ROOT/'configs/research_v1.json'))
    parser.add_argument('--start',required=True)
    parser.add_argument('--end',required=True)
    args=parser.parse_args()
    for value in [args.start, args.end]:
        try:
            if datetime.strptime(value,'%Y-%m-%d').strftime('%Y-%m-%d') != value:
                raise ValueError()
        except ValueError:
            parser.error('Dates must use YYYY-MM-DD')
    if args.end >= datetime.now(timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo('America/New_York')).strftime('%Y-%m-%d'):
        parser.error('Only completed prior sessions may enter historical research')
    config=json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    if config['symbol'] != 'US.SPY' or config['adjustment'] != 'NONE' or config['timestamp_semantics'] not in ['start','end']:
        parser.error('Unsupported data contract')
    if args.start > args.end: parser.error('Invalid date range')
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_'+uuid.uuid4().hex[:8]
    output=ROOT/'artifacts'/run_id
    output.mkdir(parents=True)
    status, error = 'SUCCESS', None
    try:
        if args.command=='doctor': doctor(args,output)
        elif args.command=='ingest': ingest(args,config)
        else: validate(args,output,config)
    except Exception as exc:
        status='FAILED_DATA'
        # Only allow predefined error identifiers, never arbitrary service payloads.
        message = str(exc)
        error=type(exc).__name__+': '+(message if message.isupper() and len(message)<80 else 'CHECK_LOCAL_DATA_OR_SERVICE')
    finally:
        git=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True)
        files={str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'data/raw').rglob('*')) if p.is_file()}
        manifest=dict(run_id=run_id,command=args.command,status=status,error=error,start=args.start,end=args.end,
                      config_sha256=sha(Path(args.config)),inputs=files,git_sha=git.stdout.strip() or 'UNCOMMITTED',
                      outputs={p.name:sha(p) for p in output.iterdir() if p.is_file()},
                      python=sys.version,packages={x:meta.version(x) for x in ['futu-api','pandas','exchange-calendars']})
        atomic(output/'manifest.json',json.dumps(manifest,indent=2))
        atomic(ROOT/'logs'/run_id/'events.jsonl',json.dumps(dict(timestamp=datetime.now(timezone.utc).isoformat(),run_id=run_id,status=status,error=error))+'\n')
    print(json.dumps(dict(run_id=run_id,status=status,error=error,output=str(output))))
    return 0 if status=='SUCCESS' else 1

if __name__=='__main__': sys.exit(main())
