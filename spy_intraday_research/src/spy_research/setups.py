"""Frozen six variants; pure event detection, no execution or performance access."""
import hashlib
import numpy as np
import pandas as pd
from .data import schedule

VARIANTS=['ORB5','ORB15','ORB30','VWAP_PULLBACK','FAILED_BREAKOUT','GAP_FADE']
EVENT_COLUMNS=['event_id','bar_id','session_date','setup','direction','signal_time','atr_prev','gap_state','volatility_state']

def detect(frame,scale=1.0):
    bars=frame.copy().reset_index(drop=True)
    for setup in VARIANTS:
        for direction in [1,-1]: bars[f'trigger_{setup}_{direction}']=False
    events=[]
    for date,group in bars.groupby('session_date',sort=False):
        chunk=group.reset_index().rename(columns={'index':'bar_id'})
        seen=set(); pending={}
        closes=chunk.close.to_numpy(); highs=chunk.high.to_numpy(); lows=chunk.low.to_numpy()
        touched_up=False; touched_down=False
        session_close=schedule(date,date).iloc[0].close
        for pos,row in chunk.iterrows():
            atr=row.atr_prev; prev=row.prev_close
            if not np.isfinite(atr) or atr<=0: continue
            touched_up=touched_up or row.low<=prev
            touched_down=touched_down or row.high>=prev
            window=row.minute_of_day>=575 and row.ts_end_utc<=session_close-pd.Timedelta(minutes=60)
            hits=[]
            for length in [5,15,30]:
                n=length//5
                if pos>=n:
                    hi=np.max(highs[:n]); lo=np.min(lows[:n])
                    if closes[pos-1]<=hi and row.close>hi: hits.append((f'ORB{length}',1))
                    if closes[pos-1]>=lo and row.close<lo: hits.append((f'ORB{length}',-1))
            if pos>=3 and row.minute_of_day>=600 and np.isfinite(row.vwap_slope):
                preceding=chunk.iloc[pos-3:pos]
                band=.02*scale*atr
                if (preceding.close>preceding.vwap).all() and row.vwap_slope>.01*scale and row.vwap-band<=row.low<=row.vwap+band and row.close>row.vwap and row.close>row.open:
                    hits.append(('VWAP_PULLBACK',1))
                if (preceding.close<preceding.vwap).all() and row.vwap_slope<-.01*scale and row.vwap-band<=row.high<=row.vwap+band and row.close<row.vwap and row.close<row.open:
                    hits.append(('VWAP_PULLBACK',-1))
            levels=[('prev_low',row.prev_low,1),('prev_high',row.prev_high,-1)]
            if row.minute_of_day>=585: levels.extend([('or_low',row.or15_low,1),('or_high',row.or15_high,-1)])
            for name,level,direction in levels:
                if not np.isfinite(level): continue
                key=(name,direction)
                if key in pending:
                    break_pos=pending[key]
                    if pos-break_pos>3: del pending[key]
                    elif pos>break_pos and direction*(row.close-level)>0:
                        hits.append(('FAILED_BREAKOUT',direction)); del pending[key]
                prior=closes[pos-1] if pos else row.open
                if key not in pending and direction*(prior-level)>=-.02*scale*atr and direction*(row.close-level)<-.02*scale*atr:
                    pending[key]=pos
            if 585<=row.minute_of_day<=630 and abs(row.gap_ratio)>=.5*scale and not row.corporate_action:
                if row.gap_ratio>0 and not touched_up and row.close<row.or15_low and row.close<row.vwap: hits.append(('GAP_FADE',-1))
                if row.gap_ratio<0 and not touched_down and row.close>row.or15_high and row.close>row.vwap: hits.append(('GAP_FADE',1))
            for setup,direction in sorted(set(hits)):
                if not window: continue
                bars.loc[row.bar_id,f'trigger_{setup}_{direction}']=True
                if (setup,direction) in seen: continue
                seen.add((setup,direction))
                identity=f'baseline_v1|US.SPY|{date}|{setup}|{direction}|{row.ts_end_utc.isoformat()}'
                events.append(dict(event_id=hashlib.sha256(identity.encode()).hexdigest()[:24],bar_id=int(row.bar_id),
                                   session_date=date,setup=setup,direction=direction,signal_time=row.ts_end_utc,
                                   atr_prev=float(atr),gap_state=row.gap_state,volatility_state=row.volatility_state))
    return bars,pd.DataFrame(events,columns=EVENT_COLUMNS)
