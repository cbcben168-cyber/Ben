"""Compare every production user table and pinned file with the preflight."""
import argparse
import hashlib
import json
from pathlib import Path

from deployment_protection import snapshot, inspect


def check(before_path, output_dir):
    before=json.loads(Path(before_path).read_text(encoding='utf-8'))
    output_dir=Path(output_dir);output_dir.mkdir(parents=True,exist_ok=True)
    result=dict(files=[],databases={},passed=True)
    for name,old_hash in before['files'].items():
        path=Path(name);actual=hashlib.sha256(path.read_bytes()).hexdigest()
        same=actual==old_hash
        result['files'].append(dict(file=str(path.relative_to(path.parents[0] if path.name=='app.py' else
            next(p for p in path.parents if p.name=='ict_trade_assistant_v04'))),sha256=actual,unchanged=same))
        result['passed'] &= same
    for name,old in before['databases'].items():
        state=snapshot(old['path'],output_dir/(name+'-after.sqlite3'))
        same_schema=old['schema']==[list(row) for row in state['schema']]
        checks={table:dict(unchanged=table in state['tables'] and state['tables'][table]['sha256']==values['sha256'],
                           before_rows=values['rows'],after_rows=len(state['tables'].get(table,{}).get('rows',[])),
                           sha256=state['tables'].get(table,{}).get('sha256')) for table,values in old['tables'].items()}
        same=bool(same_schema and set(state['tables'])==set(old['tables']) and all(v['unchanged'] for v in checks.values()))
        result['databases'][name]=dict(unchanged=same,schema_unchanged=same_schema,tables=checks)
        result['passed'] &= same
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    result=check(args.before,args.output_dir)
    with args.report.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    print('PROTECTION',result['passed'],'files',len(result['files']),'user tables',len(result['databases']['user']['tables']))
    if not result['passed']:raise SystemExit(1)
