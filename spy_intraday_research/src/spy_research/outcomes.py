"""Fixed forward horizons and conservative optional execution; no signal lookahead."""
import numpy as np
import pandas as pd

def forward(minute,events,horizons=(5,15,30,60),cost_bps=2,delay=0):
    rows=[]
    sessions={date:group.sort_values('ts_start_utc').reset_index(drop=True) for date,group in minute.groupby('session_date')}
    for event in events.itertuples():
        chunk=sessions.get(event.session_date)
        if chunk is None: continue
        starts=chunk.ts_start_utc.astype('int64').to_numpy()
        position=int(np.searchsorted(starts,pd.Timestamp(event.signal_time).value))+delay
        direction=event.direction
        for horizon in horizons:
            base=dict(event_id=event.event_id,bar_id=event.bar_id,session_date=event.session_date,
                      setup=event.setup,direction=direction,horizon=horizon,delay=delay,cost_bps=cost_bps)
            if position+horizon>len(chunk):
                rows.append(dict(**base,status='CENSORED',reason='RTH_HORIZON_INCOMPLETE')); continue
            path=chunk.iloc[position:position+horizon]
            if path.ts_start_utc.iloc[0]!=pd.Timestamp(event.signal_time)+pd.Timedelta(minutes=delay):
                rows.append(dict(**base,status='CENSORED',reason='NEXT_BAR_MISSING')); continue
            entry=path.open.iloc[0]; exit_price=path.close.iloc[-1]
            gross=direction*(exit_price/entry-1)*10000
            mfe=((path.high.max()/entry-1) if direction==1 else (1-path.low.min()/entry))*10000
            mae=((path.low.min()/entry-1) if direction==1 else (1-path.high.max()/entry))*10000
            rows.append(dict(**base,status='VALID',reason='',entry_time=path.ts_start_utc.iloc[0],
                exit_time=path.ts_end_utc.iloc[-1],entry_price=entry,exit_price=exit_price,gross_bps=gross,
                net_bps=gross-cost_bps,mfe_bps=mfe,mae_bps=mae))
    return pd.DataFrame(rows)

def simulate_path(path,direction,atr,sl_atr=None,tp_r=None,cost_bps=2):
    """Fixed hold is the baseline; TP/SL optional only after external edge gate."""
    if path.empty: raise ValueError('EMPTY_EXECUTION_PATH')
    entry=float(path.open.iloc[0]); stop=entry-direction*atr*sl_atr if sl_atr is not None else None
    target=entry+direction*atr*sl_atr*tp_r if stop is not None else None
    exit_price=float(path.close.iloc[-1]); reason='TIME'
    for row in path.itertuples():
        if stop is None: break
        if direction*(row.open-stop)<=0: exit_price=float(row.open); reason='GAP_STOP'; break
        hit_sl=row.low<=stop if direction==1 else row.high>=stop
        hit_tp=row.high>=target if direction==1 else row.low<=target
        if hit_sl: exit_price=stop; reason='STOP'; break
        if hit_tp: exit_price=target; reason='TARGET'; break
    return dict(entry_price=entry,exit_price=exit_price,reason=reason,
                gross_bps=direction*(exit_price/entry-1)*10000,net_bps=direction*(exit_price/entry-1)*10000-cost_bps)
