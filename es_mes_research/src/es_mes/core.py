"""Explicit contracts, causal roll map, UTC quality and conservative one-contract ORB."""
import re
import numpy as np
import pandas as pd
import exchange_calendars as xc

SPECS={'ES':dict(tick=.25,point_value=50.),'MES':dict(tick=.25,point_value=5.)}
RULE=dict(version='orb10_3r_futures_v1',range_minutes=10,cutoff_et='10:30_EXCLUSIVE',
          stop_fraction=.25,target_r=3,entry='NEXT_5M_OPEN',max_trades_per_day=1,
          window='XNYS_CASH_RTH_ONLY',stop_rounding='OUTWARD_TO_TICK',
          both_hit='STOP_FIRST',roll='EXPLICIT_KNOWN_BEFORE_PRIOR_CLOSE',quantity=1)


def calendar(start,end):
    return xc.get_calendar('XNYS').schedule.loc[start:end]


def utc(values):
    if not values.astype(str).str.contains(r'(?:Z|[+-]\d\d:\d\d)$',regex=True).all():
        raise ValueError('UTC_OFFSET_REQUIRED')
    return pd.to_datetime(values,utc=True,errors='raise')


def contract_ok(code,product):
    return bool(re.fullmatch(r'(?:US\.)?'+product+r'(?:\d{4}|[HMUZ]\d{1,4})',str(code)))


def validate(raw,roll,product,start,end):
    required={'ts_start_utc','open','high','low','close','volume','contract'}
    if product not in SPECS or not required.issubset(raw): raise ValueError('FUTURES_SCHEMA_INVALID')
    if not {'session_date','contract','expires_on','known_at_utc'}.issubset(roll):
        raise ValueError('ROLL_MAP_SCHEMA_INVALID')
    raw=raw.copy();roll=roll.copy();raw['ts_start_utc']=utc(raw.ts_start_utc)
    raw['ts_end_utc']=raw.ts_start_utc+pd.Timedelta(minutes=1)
    raw['session_date']=raw.ts_start_utc.dt.tz_convert('America/New_York').dt.strftime('%Y-%m-%d')
    if raw[['contract','ts_start_utc']].duplicated().any(): raise ValueError('DUPLICATE_CONTRACT_MINUTE')
    if not raw.contract.map(lambda c:contract_ok(c,product)).all():raise ValueError('EXPLICIT_CONTRACT_REQUIRED')
    prices=raw[['open','high','low','close']].apply(pd.to_numeric,errors='coerce')
    volume=pd.to_numeric(raw.volume,errors='coerce')
    good=np.isfinite(prices).all(axis=1)&(prices>0).all(axis=1)&np.isfinite(volume)&(volume>=0)
    good&=(prices.high>=prices[['open','close']].max(axis=1))&(prices.low<=prices[['open','close']].min(axis=1))
    good&=(prices.high>=prices.low)
    good&=np.isclose(prices/SPECS[product]['tick'],np.round(prices/SPECS[product]['tick']),atol=1e-7,rtol=0).all(axis=1)
    if not good.all():raise ValueError('FUTURES_PRICE_OR_TICK_INVALID')
    raw[['open','high','low','close']]=prices;raw['volume']=volume
    roll['known_at_utc']=utc(roll.known_at_utc)
    parsed_expiry=pd.to_datetime(roll.expires_on,errors='raise').dt.strftime('%Y-%m-%d')
    if not parsed_expiry.equals(roll.expires_on.astype(str)):raise ValueError('ISO_EXPIRY_DATE_REQUIRED')
    if (roll.groupby('contract').expires_on.nunique()>1).any():raise ValueError('CONFLICTING_CONTRACT_EXPIRY')
    cal=calendar(start,end)
    dates=cal.index.strftime('%Y-%m-%d').tolist()
    if not dates:raise ValueError('NO_CASH_SESSIONS')
    if roll.session_date.duplicated().any() or set(roll.session_date)!=set(dates):
        raise ValueError('ROLL_MAP_DATE_COVERAGE_INVALID')
    mapping=roll.set_index('session_date');chunks=[];prior_contract=None;prior_close=None
    for date,(_,day) in zip(dates,cal.iterrows()):
        item=mapping.loc[date]
        if not contract_ok(item.contract,product):raise ValueError('ROLL_CONTRACT_INVALID')
        if date>=str(item.expires_on):raise ValueError('EXPIRY_DAY_NOT_ALLOWED')
        if item.known_at_utc>day.open or (prior_contract is not None and item.contract!=prior_contract and item.known_at_utc>prior_close):
            raise ValueError('ROLL_LOOKAHEAD')
        chunk=raw[(raw.session_date==date)&(raw.contract==item.contract)&(raw.ts_start_utc>=day.open)&(raw.ts_end_utc<=day.close)].sort_values('ts_start_utc')
        expected=pd.date_range(day.open,day.close-pd.Timedelta(minutes=1),freq='min')
        if not chunk.ts_start_utc.reset_index(drop=True).equals(pd.Series(expected)):
            raise ValueError('INCOMPLETE_CASH_SESSION')
        if not chunk.ts_start_utc.dt.second.eq(0).all() or not chunk.ts_start_utc.dt.microsecond.eq(0).all() or not chunk.ts_start_utc.dt.nanosecond.eq(0).all():
            raise ValueError('MINUTE_ALIGNMENT_INVALID')
        chunks.append(chunk);prior_contract=item.contract;prior_close=day.close
    return pd.concat(chunks,ignore_index=True),cal


def one_day(minute,day,product,fee,slip):
    tick=SPECS[product]['tick'];point=SPECS[product]['point_value']
    minute=minute.sort_values('ts_start_utc')
    five=minute.groupby(minute.ts_start_utc.dt.floor('5min'),sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'))
    opening=five.loc[day.open:day.open+pd.Timedelta(minutes=5)]
    high=float(opening.high.max());low=float(opening.low.min());width=high-low
    base=dict(session_date=str(day.name.date()),contract=minute.contract.iloc[0],product=product,
              status='NO_TRADE',reason='NO_BREAKOUT',direction=0,or_high=high,or_low=low)
    if width<=0:return dict(**base,reason_override='ZERO_RANGE')
    ends=five.index+pd.Timedelta(minutes=5);local=ends.tz_convert('America/New_York')
    eligible=five[(five.index>=day.open+pd.Timedelta(minutes=10))&(local.hour*60+local.minute<630)]
    triggers=eligible[(eligible.close>high)|(eligible.close<low)]
    if triggers.empty:return base
    ts=triggers.index[0]+pd.Timedelta(minutes=5);direction=1 if triggers.iloc[0].close>high else -1
    raw_stop=high-.25*width if direction==1 else low+.25*width
    stop=(np.floor(raw_stop/tick) if direction==1 else np.ceil(raw_stop/tick))*tick
    path=minute[minute.ts_start_utc>=ts];raw_entry=float(path.open.iloc[0])
    base.update(direction=direction,signal_time=ts.isoformat(),stop=float(stop))
    if direction*(raw_entry-stop)<=0:return dict(**base,status_override='SKIPPED',reason_override='ENTRY_BEYOND_STOP')
    entry=raw_entry+direction*slip*tick;risk=direction*(entry-stop);target=entry+direction*3*risk
    exit_price=float(path.close.iloc[-1])-direction*slip*tick;exit_time=day.close;reason='RTH_CLOSE';both=False
    for row in path.itertuples():
        if direction*(row.open-stop)<=0:
            exit_price=float(row.open)-direction*slip*tick;exit_time=row.ts_start_utc;reason='GAP_STOP';break
        if direction*(row.open-target)>=0:
            exit_price=target;exit_time=row.ts_start_utc;reason='GAP_TARGET';break
        hit_stop=row.low<=stop if direction==1 else row.high>=stop
        # Require one tick through a profit limit; mere touch has unknown queue fill.
        hit_target=row.high>=target+tick if direction==1 else row.low<=target-tick
        if hit_stop or hit_target:
            both=bool(hit_stop and hit_target);exit_time=row.ts_end_utc
            exit_price=stop-direction*slip*tick if hit_stop else target
            reason='STOP' if hit_stop else 'TARGET';break
    gross=direction*(exit_price-entry)*point;net=gross-fee
    return dict(**base,status_override='COMPLETE',reason_override=reason,
        entry_time=ts.isoformat(),entry_price=entry,target=target,risk_usd=risk*point,
        exit_time=exit_time.isoformat(),exit_price=exit_price,gross_usd=gross,net_usd=net,
        net_r=net/(risk*point),both_hit=both,round_trip_fee_usd=fee,slippage_ticks=slip)


def run(minute,cal,product,fee,slip):
    if not np.isfinite(fee) or fee<0 or not isinstance(slip,int) or slip<0:
        raise ValueError('COSTS_INVALID')
    groups={d:g for d,g in minute.groupby('session_date')};rows=[]
    for _,day in cal.iterrows():
        r=one_day(groups[str(day.name.date())],day,product,fee,slip)
        r['status']=r.pop('status_override',r['status']);r['reason']=r.pop('reason_override',r['reason'])
        rows.append(r)
    result=pd.DataFrame(rows)
    if 'net_usd' not in result:result['net_usd']=0.
    result['net_usd']=result.net_usd.fillna(0)
    result['cumulative_usd']=result.net_usd.cumsum()
    peaks=np.maximum.accumulate(np.r_[0.,result.cumulative_usd])[1:]
    result['drawdown_usd']=result.cumulative_usd-peaks
    return result


def hold_reference(minute,product,fee,slip):
    """Explicit roll: flat previous cash close, reopen next cash open; no price splice."""
    daily=minute.groupby('session_date',sort=True).agg(contract=('contract','first'),open=('open','first'),close=('close','last'))
    daily['segment']=daily.contract.ne(daily.contract.shift()).cumsum()
    total=0.;legs=0
    for _,part in daily.groupby('segment'):
        total+=(part.close.iloc[-1]-part.open.iloc[0]-2*slip*SPECS[product]['tick'])*SPECS[product]['point_value']-fee;legs+=1
    return dict(net_usd=float(total),roll_segments=legs,model='ONE_CONTRACT_HOLD_WITH_EXPLICIT_CASH_CLOSE_OPEN_ROLL')
