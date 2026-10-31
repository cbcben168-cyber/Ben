from pathlib import Path
import sys,json,os
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from desk.provider import Provider
from desk.clock import now_et
from desk.analytics import aggregate_rth
p=Provider();d=p.fetch('US.SPY');now=now_et();root=Path(__file__).resolve().parents[1]/'data/stability';root.mkdir(exist_ok=True)
result=dict(at=now.isoformat(),health=d['health'],errors=d['errors'],raw_minutes=len(d['minute']))
for period,n in [('15m',15),('1H',60)]:
 f=aggregate_rth(d['minute'],n,now) if not d['minute'].empty else d['minute']
 f.to_csv(root/(period+'.csv'),index=False)
 result[period]=dict(rows=len(f),sample=f.tail(3).to_dict('records'))
(root/'real_periods.json').write_text(json.dumps(result,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,default=str,ensure_ascii=False),flush=True)
p.close()
os._exit(0)
