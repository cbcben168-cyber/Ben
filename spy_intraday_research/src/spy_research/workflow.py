"""Explicit staged commands. Running a report cannot change a trading rule."""
import argparse
import json
from pathlib import Path
from datetime import datetime,timezone
import traceback
import subprocess
import importlib.metadata as metadata
import pandas as pd
from .storage import write_json, atomic

ROOT=Path(__file__).resolve().parents[2]

def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['collect','prepare','register','study','evaluate','lock','freeze-diagnostic','paper','daily-review','replay'])
    parser.add_argument('--root',type=Path,default=ROOT)
    parser.add_argument('--start'); parser.add_argument('--end')
    parser.add_argument('--split',choices=['train','validation','locked_oos'],default='train')
    parser.add_argument('--lock',type=Path)
    parser.add_argument('--date'); parser.add_argument('--version',default='diagnostic_v2')
    parser.add_argument('--mode',choices=['diagnostic-shadow'],default='diagnostic-shadow')
    parser.add_argument('--once',action='store_true'); parser.add_argument('--max-cycles',type=int)
    args=parser.parse_args(argv); root=args.root.resolve()
    if args.command in ['collect','prepare','register']:
        if not args.start or not args.end: parser.error('--start and --end are required')
        for value in [args.start,args.end]:
            try:
                if datetime.strptime(value,'%Y-%m-%d').strftime('%Y-%m-%d')!=value: raise ValueError()
            except ValueError: parser.error('ISO dates required')
        if args.start>args.end or args.end>=pd.Timestamp.now(tz='America/New_York').strftime('%Y-%m-%d'):
            parser.error('Only completed prior dates are allowed')
    log=root/'logs/workflow'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    status='SUCCESS'; error=None; result=None
    try:
        if args.command=='collect':
            from .storage import collect
            collect(root,args.start,args.end)
        elif args.command=='prepare':
            from .storage import prepare
            result=prepare(root,args.start,args.end)
        elif args.command=='register':
            from .research import preregister
            result=preregister(root,args.start,args.end)
        elif args.command in ['study','evaluate']:
            from .research import evaluate
            candidates=None
            if args.split=='validation':
                previous=json.loads((root/'artifacts/research/baseline_v1/train/result.json').read_text())
                candidates=previous['candidates']
                from .research import source_hash
                if candidates and previous['source_sha256']!=source_hash(): raise ValueError('TRAIN_SOURCE_CHANGED')
            result=evaluate(root,args.split,candidates)
        elif args.command=='lock':
            from .research import lock
            result=str(lock(root))
        elif args.command=='freeze-diagnostic':
            from .shadow import freeze_diagnostic
            result=str(freeze_diagnostic(root,args.version))
        elif args.command=='paper':
            from .shadow import run
            path=args.lock or root/'locks'/args.version/'lock_manifest.json'
            run(root,path,once=args.once,max_cycles=args.max_cycles)
        elif args.command=='daily-review':
            if not args.date: parser.error('--date required')
            datetime.strptime(args.date,'%Y-%m-%d')
            from .review import daily
            result=str(daily(root,args.version,args.date))
        else:
            if not args.date: parser.error('--date required')
            from .replay import replay
            result=str(replay(root,args.date,args.version))
    except Exception as exc:
        status='FAILED'; message=str(exc)
        error=type(exc).__name__+': '+(message if message.isupper() and len(message)<100 else 'CHECK_WORKFLOW_INPUTS')
        # Stack-frame locations only: no broker response, env, or exception payload.
        frames=[dict(file=Path(f.filename).name,line=f.lineno,function=f.name) for f in traceback.extract_tb(exc.__traceback__)]
        write_json(log/'failure_frames.json',frames)
    finally:
        git=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True)
        dirty=subprocess.run(['git','status','--porcelain'],cwd=root,capture_output=True,text=True)
        package_versions={name:metadata.version(name) for name in ['futu-api','pandas','numpy','exchange-calendars','matplotlib']}
        from .research import source_hash
        manifest=dict(command=args.command,status=status,error=error,root=str(root),
                      git_sha=git.stdout.strip() or 'UNCOMMITTED',git_dirty=bool(dirty.stdout.strip()),
                      science_source_sha256=source_hash(),packages=package_versions)
        write_json(log/'manifest.json',manifest)
    print(json.dumps(dict(status=status,error=error,result=result),default=str))
    return 0 if status=='SUCCESS' else 1

if __name__=='__main__': raise SystemExit(main())
