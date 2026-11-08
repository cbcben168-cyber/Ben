"""Real saved-history evidence for v0.4.4.1; never opens a production database."""
from dataclasses import replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import pandas as pd
from desk.clock import ET
from desk.experiment import BASELINE, distance_result, replay_cutoff
from desk.history_import import DailyArchive
from desk.history_source import HistorySource
from desk.market_state import market_state
from desk.ema_layers import ema_points
from desk.decision_home import _replay_decision


def run():
    source=HistorySource(ROOT/'data/v04/history.json',datetime(2026,10,29,16,2,tzinfo=ET),
                         DailyArchive(ROOT/'data/v042/history.sqlite3'),DailyArchive(ROOT/'data/v043/updates.sqlite3'))
    wall=datetime.now(ET)
    report=dict(version='v0.4.4.1',base='3bdaa43',ema=[],replay=[],candidate={},warmup={})
    for code in ('US.SPY','US.QQQ','US.SMH'):
        data=source.fetch(code);label=data['health']['source']
        for short in (20,5):
            config=replace(BASELINE,ema_short=short)
            started=time.perf_counter()
            points=ema_points(data['daily'],'1D',wall,label,config)
            elapsed=time.perf_counter()-started
            state,_=market_state(data['daily'],'1D',wall,label,config)
            assert not points.empty and points.short.iloc[-1]==state['ema20'] and points.long.iloc[-1]==state['ema50']
            for point in points.itertuples():
                point_state,_=market_state(data['daily'],'1D',replay_cutoff(point.ts.date()),label,config)
                assert point.short==point_state['ema20'] and point.long==point_state['ema50']
            report['ema'].append(dict(symbol=code,short_span=short,long_span=50,at=state['at'],
                                      points=len(points),last_short=float(points.short.iloc[-1]),last_long=float(points.long.iloc[-1]),
                                      table_short=float(state['ema20']),table_long=float(state['ema50']),
                                      all_points_match_owner=True,compute_seconds=round(elapsed,4)))
        cutoff=replay_cutoff(datetime(2026,10,28).date())
        points=ema_points(data['daily'],'1D',cutoff,label)
        poison=data['daily'].copy();future=poison.ts>cutoff
        poison.loc[future,['open','high','low','close']]*=1000
        pd.testing.assert_frame_equal(points,ema_points(poison,'1D',cutoff,label))
        assert points.ts.max()<=cutoff
        decision=_replay_decision(code,data,cutoff)
        assert decision['ict_live_qualification']['qualified'] is False and not decision['live_review']
        report['replay'].append(dict(symbol=code,cutoff=cutoff,last_point=points.ts.max(),points=len(points),
                                     future_poison_invariant=True,live_qualified=False))
        if code=='US.QQQ':
            state,_=market_state(data['daily'],'1D',wall,label)
            before=distance_result(data,state,BASELINE,'1D')
            after=distance_result(data,state,replace(BASELINE,candidate_atr=.05),'1D')
            assert before['eligible'] is True and after['eligible'] is False
            report['candidate']=dict(symbol=code,before=before,after=after)
        if code=='US.SMH':
            assert data['minute'].empty
            assert ema_points(pd.DataFrame(),'1H',wall,label).empty
            state,_=market_state(data['daily'],'1D',wall,label)
            assert distance_result(data,state,BASELINE,'1D')['eligible'] is None
        assert ema_points(data['daily'].head(49),'1D',wall,label).empty
        assert ema_points(data['daily'],'1D',wall,'UNKNOWN').empty
    report['warmup']=dict(fewer_than_50_hidden=True,unknown_source_hidden=True,missing_1h_hidden=True)
    path=ROOT/'data/v0441-preview/real-evidence.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(result='PASS',ema_cases=len(report['ema']),replay_cases=len(report['replay']),candidate_threshold=True,
                          all_points_match=True,report=str(path)),ensure_ascii=False))


if __name__=='__main__':run()
