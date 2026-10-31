"""只按实际采样裁定本轮有界稳定性，不把短时样本外推。"""
from pathlib import Path
import json
import re
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]


def main():
    out=ROOT/'data/v03_acceptance'
    rows=[json.loads(line) for line in (out/'soak.jsonl').read_text(encoding='utf-8').splitlines()]
    browser=[json.loads(line) for line in (out/'browser-soak.jsonl').read_text(encoding='utf-8').splitlines()]
    health_failures=[r for r in rows if r.get('health')!='ok' or 'error' in r]
    pids=sorted({r.get('runtime',{}).get('pid',-1) for r in rows})
    hashes=sorted({r.get('runtime',{}).get('build_sha256','UNKNOWN') for r in rows})
    elapsed=rows[-1]['elapsed_seconds']-rows[0]['elapsed_seconds']
    interval=max((b['elapsed_seconds']-a['elapsed_seconds'] for a,b in zip(rows,rows[1:])),default=0)
    heartbeat=max(r.get('heartbeat_age_seconds',float('inf')) for r in rows)
    stable=not health_failures and len(pids)==1 and len(hashes)==1 and interval<=20 and heartbeat<=30
    refresh_times={0:set(),1:set()};lags=[];parse_errors=0
    for row in browser:
        try:
            pages,_=json.JSONDecoder().raw_decode(row['output'].split('### Result\n',1)[1])
            for page in pages:
                evaluated=re.search(r'评估 (\S+)',page['text']).group(1)
                refresh_times[page['window']].add(evaluated)
                lags.append((datetime.fromisoformat(page['at'].replace('Z','+00:00'))-datetime.fromisoformat(evaluated)).total_seconds())
        except (KeyError,ValueError,IndexError,AttributeError):parse_errors+=1
    result=dict(实际监测秒数=elapsed,采样数=len(rows),健康失败数=len(health_failures),
                最大采样间隔秒=interval,最大心跳年龄秒=heartbeat,监听进程=pids,运行指纹=hashes,
                服务结论='PASS_BOUNDED_OBSERVATION' if stable and elapsed>=3600 else 'PARTIAL',
                双窗口采样数=len(browser),双窗口实际秒数=browser[-1]['elapsed_seconds'] if browser else 0,
                双窗口失败数=sum(r.get('exit_code')!=0 or '### Error' in r.get('output','') for r in browser),
                各窗口不同评估时点数={str(k):len(v) for k,v in refresh_times.items()},
                页面评估最大滞后秒=max(lags,default=None),双窗口解析失败数=parse_errors,
                版本边界='8501为启动时V0.2.1代码，不能外推为v0.3长时通过',
                真实盘中资格='PENDING_LIVE_ACCEPTANCE')
    (out/'stability-summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('运行指纹',)},ensure_ascii=True))


if __name__=='__main__':main()
