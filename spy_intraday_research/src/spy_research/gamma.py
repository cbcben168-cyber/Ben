"""OI-based gamma model and causal SPY candidates; never broker inventory."""
import math
import numpy as np
import pandas as pd
from .data import schedule

MODEL = dict(version='gamma_levels_v1', sign='CALL_POSITIVE_PUT_NEGATIVE',
             rate=0., dividend_yield=0., iv_surface='STICKY_STRIKE',
             grid_fraction=.10, grid_points=401, fresh_seconds=120,
             expiry_scope='0DTE_AND_7_CALENDAR_DAYS', oi_asof='UNKNOWN',
             formal_data_gate=False, orders_enabled=False, hold_minutes=30,
             cost_bps=2., tp_sl_enabled=False)


def clean_chain(raw, asof):
    """Require standard SPY contracts. IV supplied by Futu is percent."""
    mapping = {'option_strike_price':'strike', 'option_open_interest':'oi',
               'option_implied_volatility':'iv', 'option_contract_size':'multiplier',
               'option_gamma':'vendor_gamma', 'option_type':'kind', 'strike_time':'expiry'}
    if not set(mapping).issubset(raw.columns) or 'code' not in raw:
        raise ValueError('GAMMA_SCHEMA_MISSING')
    frame = raw.rename(columns=mapping).copy()
    if frame.code.duplicated().any(): raise ValueError('GAMMA_DUPLICATE_CONTRACT')
    for name in ['strike','oi','iv','multiplier','vendor_gamma']:
        frame[name] = pd.to_numeric(frame[name], errors='coerce')
    frame['iv'] /= 100.
    closes = {}
    for expiry in frame.expiry.unique():
        day = schedule(str(expiry), str(expiry))
        closes[expiry] = day.iloc[0].close if len(day) else pd.NaT
    frame['expiry_utc'] = pd.to_datetime(frame.expiry.map(closes), utc=True)
    frame['years'] = (frame.expiry_utc - asof).dt.total_seconds()/(365*86400)
    numeric = frame[['strike','oi','iv','multiplier','vendor_gamma','years']]
    good = np.isfinite(numeric).all(axis=1)
    good &= (frame.strike>0)&(frame.oi>=0)&(frame.oi%1==0)&(frame.iv>0)
    good &= (frame.multiplier==100)&(frame.vendor_gamma>=0)&(frame.years>0)
    good &= frame.kind.isin(['CALL','PUT'])
    frame['valid'] = good
    return frame


def exposure(frame, prices):
    """USD delta-notional change per 1% move, BSM approximation for American SPY."""
    prices = np.asarray(prices, dtype=float)
    if (prices<=0).any() or not np.isfinite(prices).all():
        raise ValueError('GAMMA_SPOT_INVALID')
    sigma = frame.iv.to_numpy(); t = frame.years.to_numpy()
    s = prices[:,None]; k = frame.strike.to_numpy()[None,:]
    d1 = (np.log(s/k)+.5*sigma**2*t)/(sigma*np.sqrt(t))
    gamma = np.exp(-.5*d1**2)/math.sqrt(2*math.pi)/(s*sigma*np.sqrt(t))
    sign = np.where(frame.kind.to_numpy()=='CALL',1.,-1.)
    return (gamma*frame.oi.to_numpy()*frame.multiplier.to_numpy()*s*s*.01*sign).sum(axis=1)


def roots(grid, values):
    """Return every crossing within the registered grid; never extrapolate."""
    if np.all(np.asarray(values)==0): return []
    found=[]
    for i in range(len(grid)-1):
        if values[i]==0: found.append(float(grid[i]))
        elif values[i]*values[i+1]<0:
            found.append(float(grid[i]-values[i]*(grid[i+1]-grid[i])/(values[i+1]-values[i])))
    if values[-1]==0: found.append(float(grid[-1]))
    return sorted(set(found))


def levels(raw, spot, asof, spot_time, expected_codes):
    asof=pd.Timestamp(asof); spot_time=pd.Timestamp(spot_time)
    if asof.tzinfo is None or spot_time.tzinfo is None: raise ValueError('GAMMA_UTC_REQUIRED')
    spot=float(spot)
    if not np.isfinite(spot) or spot<=0: raise ValueError('GAMMA_SPOT_INVALID')
    frame=clean_chain(raw,asof)
    timestamps=pd.to_datetime(raw.update_time,errors='coerce').dt.tz_localize('America/New_York',ambiguous='NaT',nonexistent='NaT').dt.tz_convert('UTC')
    ages=(asof-timestamps).dt.total_seconds()
    spot_age=(asof-spot_time).total_seconds()
    complete=set(raw.code)==set(expected_codes) and frame.valid.all()
    fresh=bool(timestamps.notna().all() and ages.between(0,MODEL['fresh_seconds']).all()
               and 0<=spot_age<=MODEL['fresh_seconds'])
    today=asof.tz_convert('America/New_York').strftime('%Y-%m-%d')
    end=(pd.Timestamp(today)+pd.Timedelta(days=7)).strftime('%Y-%m-%d')
    grid=np.linspace(spot*.9,spot*1.1,MODEL['grid_points']); records=[]; curves=[]
    for scope,mask in [('0DTE',frame.expiry==today),('7D',(frame.expiry>=today)&(frame.expiry<=end))]:
        part=frame[mask&frame.valid].copy()
        base=dict(scope=scope,contracts=len(part),asof_utc=asof.isoformat(),spot=spot,
                  complete=bool(complete),fresh=fresh,formal_data_gate=False,
                  oi_asof='UNKNOWN',model=MODEL['version'],expected_contracts=len(expected_codes),
                  snapshot_contracts=len(raw),invalid_contracts=int((~frame.valid).sum()),
                  oldest_quote_age_seconds=float(ages.max()) if ages.notna().any() else None)
        if part.empty or not set(part.kind)=={'CALL','PUT'} or part.oi.sum()==0:
            records.append(dict(**base,status='UNAVAILABLE',gamma_zero=None,call_wall=None,put_wall=None,roots=[]));continue
        values=exposure(part,grid); crossings=roots(grid,values)
        walls={}
        # Walls use the SAME BSM gamma as the profile, not mixed vendor units.
        for kind in ['CALL','PUT']:
            group=part[part.kind==kind].copy()
            group['weight']=[abs(exposure(group.iloc[[i]],[spot])[0]) for i in range(len(group))]
            totals=group.groupby('strike').weight.sum()
            if totals.max()<=0: walls[kind]=None
            else:
                tied=totals[totals==totals.max()].index
                walls[kind]=float(sorted(tied,key=lambda k:(abs(k-spot),k))[0])
        status='DIAGNOSTIC_ONLY' if complete and fresh else 'INCOMPLETE' if not complete else 'STALE'
        selected=min(crossings,key=lambda v:abs(v-spot)) if crossings else None
        records.append(dict(**base,status=status,gamma_zero=selected,roots=crossings,
                            root_status='MULTIPLE' if len(crossings)>1 else 'ONE' if crossings else 'NO_ROOT_IN_GRID',
                            call_wall=walls['CALL'],put_wall=walls['PUT'],net_gex=float(exposure(part,[spot])[0])))
        curves.extend(dict(scope=scope,spot_price=float(p),net_gex=float(v)) for p,v in zip(grid,values))
    return records,pd.DataFrame(curves)


def candidates(bars, level, available_at, observed_at):
    """Historical captured levels only. No moving-level pseudo price crossings."""
    if level['status']!='DIAGNOSTIC_ONLY': return pd.DataFrame()
    bars=bars.sort_values('ts_end_utc').copy()
    available=pd.Timestamp(available_at); observed=pd.Timestamp(observed_at)
    if bars.empty: return pd.DataFrame()
    bars=bars[(bars.ts_start_utc>=available)&(bars.ts_end_utc<=observed)]
    rows=[]; seen=set()
    for i in range(1,len(bars)):
        previous=bars.iloc[i-1]; current=bars.iloc[i]
        if current.ts_start_utc!=previous.ts_end_utc: continue
        hits=[]
        cw=level.get('call_wall'); pw=level.get('put_wall'); zero=level.get('gamma_zero')
        positive=level.get('net_gex',0)>0
        if positive and pw is not None and previous.close>pw and current.low<=pw<current.close:
            hits.append(('PUT_WALL_BOUNCE',1,current.low,cw))
        if positive and cw is not None and previous.close<cw and current.high>=cw>current.close:
            hits.append(('CALL_WALL_REJECT',-1,current.high,pw))
        if i>=2:
            before=bars.iloc[i-2]
            if before.ts_end_utc==previous.ts_start_utc:
                if cw is not None and before.close<=cw<previous.close and current.low<=cw<current.close:
                    hits.append(('CALL_WALL_BREAK_RETEST',1,current.low,None))
                if pw is not None and before.close>=pw>previous.close and current.high>=pw>current.close:
                    hits.append(('PUT_WALL_BREAK_RETEST',-1,current.high,None))
                if zero is not None and before.close<=zero<previous.close and current.low<=zero<current.close:
                    hits.append(('GAMMA_ZERO_RECLAIM',1,current.low,cw))
                if zero is not None and before.close>=zero>previous.close and current.high>=zero>current.close:
                    hits.append(('GAMMA_ZERO_LOSS',-1,current.high,pw))
        for setup,direction,stop,target in hits:
            key=(setup,direction)
            if key in seen or direction*(current.close-stop)<=0: continue
            seen.add(key)
            if target is not None and direction*(target-current.close)<=0: target=None
            rows.append(dict(setup=setup,direction=direction,scope=level['scope'],
                signal_time=current.ts_end_utc.isoformat(),detected_at=observed.isoformat(),
                entry_not_before=(max(current.ts_end_utc,observed).floor('min')+pd.Timedelta(minutes=1)).isoformat(),
                entry_rule='NEXT_OBSERVED_1M_OPEN_NOT_SIGNAL_CLOSE',invalidation=float(stop),
                target_reference=target,exit_rule='FIXED_30M_DIAGNOSTIC_ONLY',cost_bps=2,
                status='EXPLORATORY_OI_DATE_UNKNOWN',orders_enabled=False))
    return pd.DataFrame(rows)
