"""V0.2.1 真实只读快照与双价格口径报告；独立输出，不写用户数据库。"""
from pathlib import Path
import sys,json,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desk.provider import Provider
from desk.clock import now_et
from desk.observations import SYMBOLS,build_observation,ranked,price_basis_comparison
from desk.store import DEFAULTS
OUT=ROOT/'data/v021_acceptance'

def capture():
    OUT.mkdir(exist_ok=True)
    p=Provider();obs={};evidence=[]
    try:
        for symbol in SYMBOLS:
            d=p.fetch(symbol)
            obs[symbol]=build_observation(symbol,d,DEFAULTS,now_et())
            evidence.append(dict(证券=symbol,订阅成功=symbol in p.subscribed,行情=d['health'],错误=d['errors']))
        time.sleep(2)
        for symbol in SYMBOLS:
            d=p.fetch(symbol)
            evidence.append(dict(证券=symbol,订阅成功=symbol in p.subscribed,行情=d['health'],错误=d['errors'],阶段='第二次读取'))
    finally:p.close()
    report=dict(采集时间=now_et().isoformat(),来源='真实本机 OpenD，只读行情；未使用历史回放冒充实时',
                盘中验收='PENDING_LIVE_ACCEPTANCE',原因='本次未覆盖真实 RTH；现场触价、多窗口及中断验收待完成',
                订阅与报价=evidence,观察=obs,证券排名=ranked(obs),价格口径差异=price_basis_comparison(obs),
                收盘差异裁决='未裁定；未调整原始行情')
    (OUT/'real_evidence.json').write_text(json.dumps(report,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
    import pandas as pd
    pd.DataFrame(report['价格口径差异']).to_csv(OUT/'price_basis_comparison.csv',index=False,encoding='utf-8-sig')
    print(json.dumps(dict(采集时间=report['采集时间'],证券数量=len(report['证券排名']),报价=[dict(证券=r['证券'],订阅=r['订阅成功'],资格=r['行情']['quality'],时间=r['行情'].get('quote_at'),权限=r['行情'].get('right'),年龄=r['行情'].get('age_seconds')) for r in evidence]),ensure_ascii=False))

if __name__=='__main__':capture()
