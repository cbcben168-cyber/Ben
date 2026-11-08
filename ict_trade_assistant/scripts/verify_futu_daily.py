"""Real saved-data acceptance with the unchanged v0.4.4.1 calculations."""
import argparse
from dataclasses import asdict, replace
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sys

import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from capture_futu_daily import SYMBOLS
from desk.futu_daily import FutuDailyArchive, CONTRACT, verify_payload
from desk.experiment import BASELINE, replay_cutoff
from desk.market_state import market_state
from desk.ema_layers import ema_points
from desk.ict_live_gate import ict_live_qualification


def verify(database):
    archive=FutuDailyArchive(database)
    asof=replay_cutoff(pd.Timestamp('2026-11-06').date())
    experiment=replace(BASELINE,ema_short=5,ema_long=35,atr_period=20)
    rows=[]
    for ticker in SYMBOLS:
        meta,frame=archive.read('US.'+ticker)
        state,_=market_state(frame,'1D',asof,CONTRACT)
        other,_=market_state(frame,'1D',asof,CONTRACT,experiment)
        points=ema_points(frame,'1D',asof,CONTRACT)
        changed=ema_points(frame,'1D',asof,CONTRACT,experiment)
        assert len(frame)==90 and meta['last']=='2026-11-06' and not meta['missing']
        assert meta['status']=='PASS' and meta['max_ohlc_error']<=.000001
        assert state['trend']!='UNKNOWN' and other['trend']!='UNKNOWN'
        assert len(points)==len(changed)==41
        assert points.short.iloc[-1]==state['ema20'] and points.long.iloc[-1]==state['ema50']
        assert changed.short.iloc[-1]==other['ema20'] and changed.long.iloc[-1]==other['ema50']
        # Future candle poisoning cannot change a replay result or EMA endpoint.
        cutoff=replay_cutoff(pd.Timestamp('2026-11-04').date())
        normal,_=market_state(frame,'1D',cutoff,CONTRACT)
        poison=frame.copy();poison.loc[poison.ts>cutoff,['open','high','low','close']]=999999.
        assert market_state(poison,'1D',cutoff,CONTRACT)[0]==normal
        pd.testing.assert_frame_equal(ema_points(poison,'1D',cutoff,CONTRACT),ema_points(frame,'1D',cutoff,CONTRACT))
        assert market_state(frame.head(49),'1D',asof,CONTRACT)[0]['trend']=='UNKNOWN'
        assert ema_points(frame.head(49),'1D',asof,CONTRACT).empty
        keys=('ema20','ema50','atr14','trend','volatility','sample_bars')
        rows.append(dict(symbol=ticker,bars=len(frame),last=meta['last'],source=CONTRACT,
                         capture_sha256=meta['capture_sha256'],adjustment_check=meta,
                         baseline={k:state[k] for k in keys},experiment={k:other[k] for k in keys},
                         ema_points=len(points),future_poisoning_invariant=True))
        if ticker=='SOXX':
            with closing(archive.connect()) as db:
                payload=json.loads(db.execute('SELECT payload FROM captures WHERE sha256=?',
                                              (meta['capture_sha256'],)).fetchone()[0])
            raw=frame.copy()
            for field in ('open','high','low','close','volume'):
                raw[field]=[r[field] for r in payload['responses']['NONE']['records']]
            raw_state,_=market_state(raw,'1D',asof,'FUTU_OPEND/K_DAY/RTH/NONE')
            index=frame.index[frame.ts.dt.date==pd.Timestamp('2026-11-05').date()][0]
            soxx=dict(pre_split_day='2026-11-04',split_day='2026-11-05',ratio='1:3',
                      raw_previous_close=float(raw.close.iloc[index-1]),
                      qfq_previous_close=float(frame.close.iloc[index-1]),
                      split_day_close=float(frame.close.iloc[index]),
                      raw_close_return=float(raw.close.iloc[index]/raw.close.iloc[index-1]-1),
                      qfq_close_return=float(frame.close.iloc[index]/frame.close.iloc[index-1]-1),
                      raw_atr14_diagnostic=raw_state['atr14'],qfq_atr14=state['atr14'],
                      note='NONE对照仅诊断拆股机械断层；实际分析始终使用整批QFQ，不消除真实市场波动。')
            assert abs(soxx['qfq_previous_close']-soxx['raw_previous_close']/3)<.000001
            assert soxx['raw_close_return']<-.6 and soxx['qfq_close_return']>-.4
    return dict(status='PASS',symbols=23,bars=2070,analysis_asof_utc=pd.Timestamp(asof).tz_convert('UTC').isoformat(),
                baseline=asdict(BASELINE),experiment=asdict(experiment),rows=rows,soxx=soxx,
                database_sha256=hashlib.sha256(Path(database).read_bytes()).hexdigest(),
                frozen_ict_qualified=ict_live_qualification({}, {}, asof)['qualified'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=verify(args.database)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as stream:
        json.dump(result,stream,ensure_ascii=False,indent=2)
    print('PASS: 23 symbols / 2070 bars / frozen calculations / replay / QFQ / ICT gate=false')
