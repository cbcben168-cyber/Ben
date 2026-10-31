"""核实本地真实历史快照并检查事件因果顺序；不计算策略收益。"""
from pathlib import Path
import sys
import json
import hashlib
from collections import Counter
from datetime import timedelta
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desk.ict_v03 import scan, VERSION, PARAMETERS
from desk.clock import bounds


def main():
    source=ROOT/'data/v02_acceptance/real_snapshots.json'
    out=ROOT/'data/v03_acceptance';out.mkdir(exist_ok=True)
    saved=json.loads(source.read_text(encoding='utf-8'))
    report=dict(策略版本=VERSION,参数=PARAMETERS,来源文件=str(source),
                来源SHA256=hashlib.sha256(source.read_bytes()).hexdigest(),
                证据边界='本地既有OpenD历史快照；供应商最终性及取得时点的逐分钟可用性未验证；不是实盘验收',
                真实盘中资格='PENDING_LIVE_ACCEPTANCE',证券={})
    for symbol in ['US.SPY','US.QQQ','US.IWM','US.SOXX']:
        frame=pd.DataFrame(saved[symbol]['minute'])
        frame['ts']=pd.to_datetime(frame.ts,utc=True).dt.tz_convert('America/New_York')
        assert set(frame.source)=={'FUTU_OPEND'}, '来源不是既有OpenD快照'
        last_day=frame[frame.session=='RTH'].ts.max().date()
        cutoff=bounds(last_day)[1]+timedelta(minutes=2)
        r=scan(symbol,frame,cutoff)
        assert r['status']=='AVAILABLE'
        assert len({e['id'] for e in r['events']})==len(r['events'])
        assert r==scan(symbol,frame,cutoff), '重复运行不确定'
        checks=[]
        for event in r['events']:
            if event['status']!='CONFIRMED':continue
            known=pd.Timestamp(event['confirmed_at'])
            assert known<=cutoff
            for candle in event['evidence']:
                if not all(k in candle for k in ['open','high','low','close']):continue
                start,end=pd.Timestamp(candle['ts']),pd.Timestamp(candle['end'])
                raw=frame[(frame.session=='RTH')&(frame.ts>=start)&(frame.ts<end)].sort_values('ts')
                assert len(raw)==candle['minutes']
                assert (candle['open'],candle['high'],candle['low'],candle['close'])==(float(raw.open.iloc[0]),float(raw.high.max()),float(raw.low.min()),float(raw.close.iloc[-1]))
            if event['kind']=='SWEEP':
                day=pd.Timestamp(event['occurred_at']).date()
                from desk.clock import previous_day
                prior=frame[(frame.session=='RTH')&(frame.ts.dt.date==previous_day(day))]
                assert len(prior)==390
                expected=float(prior.low.min()) if event['direction']=='LONG' else float(prior.high.max())
                assert event['level']==expected
            if event['kind']=='MSS':
                sweep=next(e for e in r['events'] if e['id']==event['associated_sweep'])
                assert pd.Timestamp(event['pivot_known_at'])<=pd.Timestamp(sweep['confirmed_at'])<=known
                assert event['evidence'][-1]['close']>event['structure_price'] if event['direction']=='LONG' else event['evidence'][-1]['close']<event['structure_price']
            if event['kind']=='FVG':
                a,b,c=event['evidence']
                expected=(a['high'],c['low']) if event['direction']=='LONG' else (c['high'],a['low'])
                assert (event['low'],event['high'])==expected and event['ce']==sum(expected)/2
            checks.append(event['id'])
        # 在真实数据中按不同形成/确认时点做as-of前缀一致性，不仅检查最终结果。
        prefix_times=[]
        for offset in [59,61,62,122,182,389,392]:
            t=bounds(last_day)[0]+timedelta(minutes=offset)
            full=scan(symbol,frame,t)
            prefix=scan(symbol,frame[frame.ts<t],t)
            assert full==prefix
            prefix_times.append(t.isoformat())
        days=[]
        for day,g in frame[frame.session=='RTH'].groupby(frame[frame.session=='RTH'].ts.dt.date):
            start,end=bounds(day);expected=pd.date_range(start,end,freq='min',inclusive='left')
            days.append(dict(日期=str(day),实际分钟=len(g),预期分钟=len(expected),完整=set(g.ts)==set(expected) and len(g)==len(expected)))
        (out/(symbol[3:]+'-events.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2),encoding='utf-8')
        pd.DataFrame(r['events']).to_csv(out/(symbol[3:]+'-events.csv'),index=False,encoding='utf-8-sig')
        report['证券'][symbol]=dict(分钟数=len(frame),RTH完整性=days,截止=cutoff.isoformat(),完整1H柱=r['completed_bars'],
                                  事件计数=dict(Counter(e['kind'] for e in r['events'])),独立FVG数=len(r['fvgs']),
                                  唯一事件数=len(r['events']),价格时间断言数=len(checks),前缀一致性时点=prefix_times,缺失分桶=r['gap_count'])
    (out/'offline-evidence.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
