"""Causal market state; fitted boundaries are Train-only."""
import numpy as np
import pandas as pd
from .data import schedule

def wilder(values, period=14):
    result=np.full(len(values),np.nan)
    if len(values)>=period:
        result[period-1]=np.mean(values[:period])
        for i in range(period,len(values)): result[i]=(result[i-1]*(period-1)+values[i])/period
    return result

def build(minute,five,actions):
    daily=minute.groupby('session_date',sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'))
    # Missing session breaks previous-day references rather than silently skipping.
    calendar=schedule(daily.index[0],daily.index[-1])
    dates=[x.strftime('%Y-%m-%d') for x in calendar.index]
    daily=daily.reindex(dates)
    previous=daily.close.shift(1)
    true_range=pd.concat([daily.high-daily.low,(daily.high-previous).abs(),(daily.low-previous).abs()],axis=1).max(axis=1)
    # Restart warmup after any missing day; no filling through quarantines.
    daily['atr_prev']=np.nan
    valid=daily.close.notna()
    groups=(~valid).cumsum()
    for _,part in daily[valid].groupby(groups[valid]):
        daily.loc[part.index,'atr_prev']=pd.Series(wilder(true_range.loc[part.index].to_numpy()),index=part.index).shift(1)
    daily['prev_close']=previous
    daily['prev_high']=daily.high.shift(1); daily['prev_low']=daily.low.shift(1)
    daily['volatility']=daily.atr_prev/daily.prev_close
    daily['gap_ratio']=(daily.open-daily.prev_close)/daily.atr_prev
    daily['corporate_action']=daily.index.isin(actions)
    frame=five.merge(daily[['atr_prev','prev_close','prev_high','prev_low','volatility','gap_ratio','corporate_action']],
                     left_on='session_date',right_index=True,how='left').sort_values('ts_end_utc').reset_index(drop=True)
    frame['available_at_utc']=frame.ts_end_utc
    frame['bucket']=frame.ts_end_utc.dt.tz_convert('America/New_York').dt.strftime('%H:%M')
    frame['minute_of_day']=frame.ts_end_utc.dt.tz_convert('America/New_York').dt.hour*60+frame.ts_end_utc.dt.tz_convert('America/New_York').dt.minute
    frame['vwap']=np.nan; frame['or15_high']=np.nan; frame['or15_low']=np.nan
    frame['or_ratio']=np.nan; frame['opening_direction']='UNKNOWN'; frame['vwap_slope']=np.nan
    for _,chunk in frame.groupby('session_date',sort=False):
        weight=chunk.volume.cumsum()
        vwap=(((chunk.high+chunk.low+chunk.close)/3)*chunk.volume).cumsum()/weight.replace(0,np.nan)
        frame.loc[chunk.index,'vwap']=vwap
        frame.loc[chunk.index,'vwap_slope']=(vwap-vwap.shift(3))/chunk.atr_prev
        if len(chunk)>=3:
            first=chunk.iloc[:3]; high=first.high.max(); low=first.low.min()
            available=chunk.index[chunk.minute_of_day>=585]
            frame.loc[available,'or15_high']=high; frame.loc[available,'or15_low']=low
            atr=chunk.atr_prev.iloc[0]
            frame.loc[available,'or_ratio']=(high-low)/atr if atr>0 else np.nan
            ratio=(first.close.iloc[-1]-first.open.iloc[0])/(high-low) if high>low else np.nan
            frame.loc[available,'opening_direction']='Trend Up' if ratio>=0.5 else 'Trend Down' if ratio<=-0.5 else 'Mixed' if np.isfinite(ratio) else 'UNKNOWN'
    baseline=frame.groupby('bucket',sort=False).volume.transform(lambda x:x.shift(1).rolling(20,min_periods=20).median())
    frame['volume_expansion']=frame.volume/baseline.replace(0,np.nan)
    frame['relative_price']=(frame.close-frame.vwap)/frame.atr_prev
    absolute=frame.gap_ratio.abs()
    frame['gap_state']=np.where(absolute<=0.1,'Flat',np.where(absolute<0.5,'Small','Large'))
    frame['gap_state']=np.where(absolute<=0.1,'Flat',frame.gap_state+np.where(frame.gap_ratio>0,' Up',' Down'))
    frame.loc[frame.gap_ratio.isna(),'gap_state']='UNKNOWN'
    frame['vwap_state']=np.select([frame.vwap_slope>0.01,frame.vwap_slope<-.01,frame.vwap_slope.notna()],['Rising','Falling','Flat'],default='UNKNOWN')
    return frame

def fit_states(frame,train_dates):
    train=frame[frame.session_date.isin(train_dates)]
    daily=train.drop_duplicates('session_date')
    ors=train[train.or_ratio.notna()].drop_duplicates('session_date')
    model={}
    for name,series in [('volatility',daily.volatility),('or_ratio',ors.or_ratio)]:
        clean=series.dropna()
        if clean.empty: raise ValueError('FEATURE_WARMUP_INSUFFICIENT')
        model[name]=dict(low=float(clean.quantile(1/3)),high=float(clean.quantile(2/3)))
    # Only pre-trigger gap / lagged volatility used for caliper matching.
    model['matching_scale']={name:float(daily[name].std(ddof=1)) for name in ['gap_ratio','volatility']}
    return model

def apply_states(frame,model):
    frame=frame.copy()
    for column,target,labels in [('volatility','volatility_state',['Low','Normal','High']),('or_ratio','or_state',['Narrow','Normal','Wide'])]:
        limits=model[column]; value=frame[column]
        frame[target]=np.select([value<limits['low'],value<=limits['high'],value.notna()],labels,default='UNKNOWN')
    return frame
