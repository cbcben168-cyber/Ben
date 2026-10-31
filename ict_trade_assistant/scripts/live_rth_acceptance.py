"""只读、手动、有界RTH验收采集；默认只显示计划，不连接OpenD。"""
from pathlib import Path
import argparse
import hashlib
import json
import sqlite3
import sys
import time
from copy import deepcopy
from zoneinfo import ZoneInfo
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desk.clock import now_et, session
from desk.store import DEFAULTS
from desk.observations import SYMBOLS, build_observation, ranked


def read_user_state():
    """只读打开已有库，不初始化、不迁移、不写入。"""
    settings=deepcopy(DEFAULTS);fingerprints={}
    with sqlite3.connect((ROOT/'data/desk.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        for key,value in db.execute('SELECT key,value FROM settings'):
            if key in settings:settings[key]=json.loads(value)
        for table in ['notes','plan_versions','settings','events','acknowledgements']:
            rows=db.execute(f'SELECT * FROM {table} ORDER BY rowid').fetchall()
            fingerprints[table]=dict(rows=len(rows),sha256=hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode()).hexdigest())
    return settings,fingerprints


def plan():
    monday=datetime(2026,11,2,9,30,tzinfo=ZoneInfo('America/New_York'))
    return dict(真实盘中资格='PENDING_LIVE_ACCEPTANCE',纽约时区='America/New_York',
                星期一开盘=monday.isoformat(),香港时间=monday.astimezone(ZoneInfo('Asia/Hong_Kong')).isoformat(),
                当前时间=now_et().isoformat(),当前时段=session(now_et()),
                说明='默认不连接OpenD；开盘后由用户手动添加--capture；无自动任务，无账户或订单调用')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture',action='store_true',help='仅在真实RTH手动采集，只读行情')
    parser.add_argument('--samples',type=int,default=5)
    parser.add_argument('--interval',type=int,default=30)
    parser.add_argument('--output',type=Path,default=ROOT/'data/live_rth_acceptance')
    args=parser.parse_args()
    if not (1<=args.samples<=20 and 1<=args.interval<=60):parser.error('样本数1至20，间隔1至60秒')
    report=plan()
    if not args.capture or session(now_et())!='RTH':
        print(json.dumps(report,ensure_ascii=False,indent=2));return
    args.output.mkdir(parents=True,exist_ok=True)
    run=args.output/now_et().strftime('%Y%m%dT%H%M%S%z');run.mkdir(exist_ok=False)
    settings,before=read_user_state()
    from desk.provider import Provider
    provider=Provider();samples=[]
    try:
        for i in range(args.samples):
            if session(now_et())!='RTH':break
            observations={};quotes={}
            for symbol in SYMBOLS:
                data=provider.fetch(symbol);at=now_et()
                observations[symbol]=build_observation(symbol,data,settings,at)
                health=observations[symbol]['health']
                quotes[symbol]={k:health.get(k) for k in ['quote_at','received_at','price','quality','reason','right','source','age_seconds','server_clock_skew_seconds']}
            ranked_rows=ranked(observations)
            samples.append(dict(序号=i,采集完成=now_et().isoformat(),报价=quotes,观察=observations,证券排名=ranked_rows,
                                同证券去重=len({r['symbol'] for r in ranked_rows})==len(ranked_rows)))
            # 每样本落盘，SDK超时或人工中断时保留已完成证据。
            (run/'samples.json').write_text(json.dumps(samples,ensure_ascii=False,default=str,indent=2),encoding='utf-8')
            if i+1<args.samples:time.sleep(args.interval)
    finally:
        provider.close()
        _,after=read_user_state()
        report.update(样本数=len(samples),用户记录前=before,用户记录后=after,
                      保留项目='采集脚本不写用户库；同时运行看板可能产生真实系统或市场事件，差异需逐条核对',
                      状态='已保存只读样本，完整盘中验收仍需人工清单逐项裁定',
                      尚待人工验收=['自然NEAR/INSIDE/OUTSIDE变化与提醒去重','双窗口和备注','断线有限恢复','开收盘模式切换'],
                      说明='不因有新报价便自动授予ICT提醒资格；未创建后台任务')
        (run/'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(str(run))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
