"""Past-data integration replay, isolated from future paper cumulative statistics."""
import json
import pandas as pd
from .storage import normalized, write_json
from .research import corporate_dates
from .shadow import Session
from .data import schedule

def replay(root,date,version='diagnostic_v2'):
    lock=json.loads((root/'locks'/version/'lock_manifest.json').read_text())
    lock['version']='replay_'+version
    lock['account_processing_delay']=False
    minute,_,_=normalized(root)
    prior=minute[minute.session_date<date]
    warmup_dates=sorted(prior.session_date.unique())[-60:]
    prior=prior[prior.session_date.isin(warmup_dates)]
    day=minute[minute.session_date==date].sort_values('ts_start_utc')
    if day.empty: raise ValueError('REPLAY_DATE_UNAVAILABLE')
    folder=root/'artifacts/paper'/lock['version']/date
    if folder.exists(): raise ValueError('REPLAY_ALREADY_EXISTS')
    runner=Session(root,lock,date,prior,corporate_dates(root))
    # Each completed 5m bar is revealed at +3sec. The contemporaneous close proxy
    # is synthetic replay input, not a claim about historical executable quotes.
    for pos in range(4,len(day),5):
        prefix=day.iloc[:pos+1]
        now=prefix.ts_end_utc.iloc[-1]+pd.Timedelta(seconds=3)
        quote=dict(timestamp=now,price=float(prefix.close.iloc[-1]))
        runner.step(prefix,quote,now)
    review=runner.finish(schedule(date,date).iloc[0].close+pd.Timedelta(minutes=1),final_bars=day)
    write_json(folder/'REPLAY_ONLY.json',dict(mode='REPLAY_SYNTHETIC_QUOTE_PROXY',date=date,
                                            no_broker_fills=True,not_future_test=True))
    return review
