"""独立1H历史观察器；不生成订单、收益或实时入场建议。"""
import hashlib
import json
import math
from datetime import timedelta
import pandas as pd
from .clock import ET, CAL, bounds, previous_day

VERSION = 'ICT-OBS-1H-v0.3'
PARAMETERS = dict(pivot_left=2, pivot_right=2, mss_bars=4, fvg_bars=6,
                  ce_bars=6, ce_fraction=.5, atr_period=14, stop_atr=.1,
                  quarantine_minutes=2, liquidity='PREVIOUS_FULL_RTH', one_sweep_per_day=True)
PARAMETER_VERSION = hashlib.sha256(json.dumps(PARAMETERS, sort_keys=True).encode()).hexdigest()[:16]


def live_alert_allowed(*, enabled=False, qualified=False):
    return bool(enabled and qualified)


def _iso(ts):
    return pd.Timestamp(ts).isoformat()


def _evidence(bar):
    return {k: _iso(v) if k in ('ts', 'end', 'known_at') else v
            for k, v in bar.items() if k in ('ts','end','known_at','open','high','low','close','source','minutes')}


def _zone_state(zone, state, bar, reason):
    if zone.get('transitions') and zone['status']==state:return
    zone['status']=state
    zone.setdefault('transitions',[]).append(dict(state=state,occurred_at=_iso(bar['end']),
        confirmed_at=_iso(bar['known_at']),source=bar.get('source','XNYS_CALENDAR / MISSING_RTH_MINUTES'),
        trigger=reason,version=VERSION,parameter_version=PARAMETER_VERSION,evidence=[_evidence(bar)]))
    if state=='INVALIDATED':
        zone.update(invalidation_reason=reason,invalidated_at=_iso(bar['known_at']))


def _input(frame, now):
    if now.tzinfo is None:
        raise ValueError('评估时间必须带时区')
    required = {'ts','open','high','low','close','volume','session','eligible','source'}
    if frame.empty or not required.issubset(frame.columns):
        raise ValueError('分钟证据缺失')
    f = frame.copy()
    if f.ts.dt.tz is None:
        raise ValueError('分钟时间缺少时区')
    f['ts'] = f.ts.dt.tz_convert(ET)
    f = f[(f.ts < now) & (f.session == 'RTH')].sort_values('ts')
    if f.empty or f.ts.duplicated().any():
        raise ValueError('分钟为空或时间重复')
    if not f.ts.map(lambda t: t.second == 0 and t.microsecond == 0 and bool(bounds(t.date()))
                    and bounds(t.date())[0] <= t < bounds(t.date())[1]).all():
        raise ValueError('分钟时间不符合RTH日历')
    for col in ['open','high','low','close','volume']:
        if not f[col].map(lambda v: isinstance(v,(int,float)) and math.isfinite(v)).all():
            raise ValueError('分钟OHLCV不是有限数值')
    if ((f.low <= 0) | (f.low > f[['open','close']].min(axis=1)) |
            (f.high < f[['open','close']].max(axis=1)) | (f.volume < 0)).any():
        raise ValueError('分钟OHLCV无效')
    if f.source.isna().any() or (f.source.astype(str).str.len()==0).any():
        raise ValueError('分钟来源未知')
    # 历史缓存中的eligible不能替代本次as-of时间检查。
    f['usable'] = f.eligible.eq(True) & (f.ts + pd.Timedelta(minutes=3) <= now)
    return f


def _bars(frame, now):
    bars, levels = [], {}
    days = CAL.sessions_in_range(str(frame.ts.iloc[0].date()), str(now.astimezone(ET).date()))
    for label in days:
        day = label.date(); start, end = bounds(day)
        raw = frame[(frame.ts.dt.date == day) & frame.usable]
        expected = pd.date_range(start,end,freq='min',inclusive='left')
        if end-start == timedelta(minutes=390) and len(raw)==390 and set(raw.ts)==set(expected):
            levels[day] = dict(ts=start,end=end,minutes=390,open=float(raw.open.iloc[0]),close=float(raw.close.iloc[-1]),
                               high=float(raw.high.max()),low=float(raw.low.min()),
                               known_at=end+timedelta(minutes=2),source=' + '.join(sorted(set(raw.source))))
        while start < end and start < now:
            finish = min(start+timedelta(hours=1),end)
            part = raw[(raw.ts >= start) & (raw.ts < finish)]
            grid = pd.date_range(start,finish,freq='min',inclusive='left')
            known = finish+timedelta(minutes=2)
            complete = len(part)==len(grid) and set(part.ts)==set(grid) and now>=known
            bar = dict(ts=start,end=finish,known_at=known,complete=complete,source='XNYS_CALENDAR / MISSING_RTH_MINUTES',
                       gap=now>=known,minutes=len(grid),day=day)
            # 形成中数据只含当时已经完整并经过隔离的分钟。
            if not part.empty:
                bar.update(open=float(part.open.iloc[0]),high=float(part.high.max()),low=float(part.low.min()),
                           close=float(part.close.iloc[-1]),source=' + '.join(sorted(set(part.source))))
            bars.append(bar);start=finish
    return bars, levels


def scan(symbol, minute, now, timeframe='1H'):
    result = dict(version=VERSION, parameter_version=PARAMETER_VERSION, parameters=PARAMETERS.copy(),
                  symbol=symbol,timeframe=timeframe,status='UNKNOWN',reason='',events=[],pivots=[],fvgs=[],sweeps=[],
                  live_alerts_enabled=False,live_qualification='PENDING_LIVE_ACCEPTANCE',
                  finality='VENDOR_FINALITY_UNVERIFIED',mode='HISTORICAL_OBSERVATION')
    if timeframe!='1H':
        result['reason']='4H与日线自动识别未启用，等待独立聚合和确认时点验收'
        return result
    try:
        f=_input(minute,now); bars,levels=_bars(f,now)
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError) as exc:
        result['reason']=str(exc);return result
    events=result['events']; pivots=result['pivots']; zones=result['fvgs']
    history=[]; active=None; seen=set(); watched=set(); gap_count=0

    def emit(kind,state,bar,setup,status='CONFIRMED',reason='',**payload):
        occurred=min(bar['end'],now) if status=='FORMING' else bar['end']
        confirmed=bar['known_at'] if status=='CONFIRMED' else None
        identity=f'{VERSION}|{symbol}|{setup}|{kind}|{_iso(occurred)}|{status}'
        event=dict(id=hashlib.sha256(identity.encode()).hexdigest()[:24],setup_id=setup,kind=kind,state=state,timeframe='1H',
                   status=status,symbol=symbol,direction=payload.pop('direction','UNKNOWN'),
                   occurred_at=_iso(occurred),bar_end=_iso(bar['end']),confirmed_at=_iso(confirmed) if confirmed else None,
                   source=bar.get('source','RTH_MINUTE_EVIDENCE'),version=VERSION,parameter_version=PARAMETER_VERSION,
                   reason=reason,invalidation_reason=reason if state=='INVALIDATED' else '',
                   trigger=reason,evidence=[_evidence(bar)],**payload)
        events.append(event);return event

    def cancel(bar,reason):
        nonlocal active
        emit('INVALIDATED','INVALIDATED',bar,active['id'],reason=reason,direction=active['direction'])
        if active.get('zone'):_zone_state(active['zone'],'INVALIDATED',bar,reason)
        active=None

    for bar in bars:
        day=bar['day']; prior=levels.get(previous_day(day)); legal=bool(prior and prior['known_at']<=bar['ts'] and bounds(day)[1]-bounds(day)[0]==timedelta(minutes=390))
        if legal and day not in watched:
            watched.add(day)
            for direction,side in [('LONG','low'),('SHORT','high')]:
                key=f'{day}|{direction}|{prior[side]:g}'
                watch=dict(ts=bounds(day)[0],end=bounds(day)[0],known_at=bounds(day)[0],source=prior['source'])
                event=emit('WATCH','WATCH',watch,key,reason='上个正常RTH完整390分钟，前日高低点在当前开盘前已知',direction=direction,level=prior[side],level_known_at=_iso(prior['known_at']))
                event['evidence']=[_evidence(prior)]
        if not bar['complete']:
            if bar['gap']:
                gap_count+=1
                if active:cancel(bar,'预期RTH分钟缺失或未通过完整性检查，关闭观察链')
                for z in zones:
                    if z['status']!='INVALIDATED':
                        _zone_state(z,'INVALIDATED',bar,'预期RTH分钟缺失，缺口观察关闭')
                history=[]
            elif legal and day not in seen and 'low' in bar:
                for direction,side in [('LONG','low'),('SHORT','high')]:
                    crossed=bar['low']<prior[side] if direction=='LONG' else bar['high']>prior[side]
                    if crossed:
                        emit('SWEEP','WATCH',bar,f'{day}|{direction}|{prior[side]:g}',status='FORMING',
                             reason='已完成分钟越过前日水平，1H尚未完成或未过隔离期',direction=direction,level=prior[side],extreme=bar['low'] if direction=='LONG' else bar['high'])
            continue
        # 当前bar以前的已确认pivot；右2根真正完成后才公开。
        history.append(bar)
        # 独立识别全部方向FVG，不把未关联MSS的缺口当作完整SOP链。
        for z in zones:
            if z['status']=='INVALIDATED':continue
            z['age']+=1
            broken=bar['close']<z['low'] if z['direction']=='LONG' else bar['close']>z['high']
            if broken or z['age']>PARAMETERS['ce_bars']:
                _zone_state(z,'INVALIDATED',bar,'收盘越过远端边界' if broken else '6根完整K线观察期限结束')
            elif bar['low']<=z['high'] and bar['high']>=z['low']:
                _zone_state(z,'TOUCHED',bar,'形成柱之后的完整K线区间与FVG相交')
                if not z.get('touched_at'):z['touched_at']=_iso(bar['known_at'])
                if bar['low']<=z['ce']<=bar['high'] and not z.get('ce_touched_at'):
                    z['ce_touched_at']=_iso(bar['known_at'])
            elif z['status']=='NEW':_zone_state(z,'WAITING_RETEST',bar,'后续完整K线尚未回踩FVG')
        if len(history)>=3:
            a,b,c=history[-3:]
            for direction in ['LONG','SHORT']:
                gap=(c['low']>a['high'] and b['close']>b['open']) if direction=='LONG' else (c['high']<a['low'] and b['close']<b['open'])
                if gap:
                    low,high=(a['high'],c['low']) if direction=='LONG' else (c['high'],a['low'])
                    zones.append(dict(id=f'{symbol}|{_iso(c["end"])}|{direction}',setup_id=None,direction=direction,
                                      low=low,high=high,ce=(low+high)/2,status='NEW',age=0,occurred_at=_iso(c['end']),
                                      confirmed_at=_iso(c['known_at']),source=c['source'],version=VERSION,parameter_version=PARAMETER_VERSION,
                                      evidence=[_evidence(x) for x in (a,b,c)],invalidation_reason=''))
                    _zone_state(zones[-1],'NEW',c,'第三根完整K线确认方向FVG')
        if len(history)>=5:
            window=history[-5:];center=window[2]
            for side in ['high','low']:
                strict=all(center[side]>x[side] if side=='high' else center[side]<x[side] for x in window if x is not center)
                if strict:
                    pivots.append(dict(side=side,price=center[side],occurred_at=_iso(center['ts']),known_at=_iso(bar['known_at']),evidence=[_evidence(x) for x in window]))
        if active:
            active['age']+=1
            direction=active['direction'];long=direction=='LONG'
            if (bar['low']<=active['stop'] if long else bar['high']>=active['stop']):
                cancel(bar,'已完成K线触及Sweep极值加ATR缓冲失效价；同柱优先失效')
            elif active.get('zone') and (bar['close']<active['zone']['low'] if long else bar['close']>active['zone']['high']):
                cancel(bar,'收盘越过FVG远端边界，缺口观察失效')
            elif active['state']=='SWEEP':
                if active['age']>PARAMETERS['mss_bars']:cancel(bar,'Sweep后4根完整K线内未确认MSS')
                elif active['pivot'] and (bar['close']>active['pivot']['price'] if long else bar['close']<active['pivot']['price']):
                    active.update(state='MSS',mss_index=len(history)-1,age=0)
                    emit('MSS','MSS',bar,active['id'],reason='收盘严格突破Sweep确认时已知且固定的Swing Pivot',direction=direction,
                         structure_price=active['pivot']['price'],pivot_known_at=active['pivot']['known_at'],associated_sweep=active['sweep'],pivot_evidence=active['pivot']['evidence'])
            if active and active['state']=='MSS':
                if active['age']>=PARAMETERS['fvg_bars']:cancel(bar,'MSS当根起6根K线内未形成方向FVG')
                elif len(history)>=3:
                    a,b,c=history[-3:]
                    gap=(c['low']>a['high'] and b['close']>b['open']) if long else (c['high']<a['low'] and b['close']<b['open'])
                    if gap:
                        low,high=(a['high'],c['low']) if long else (c['high'],a['low'])
                        zone=next(z for z in reversed(zones) if z['confirmed_at']==_iso(c['known_at']) and z['direction']==direction)
                        zone['setup_id']=active['id'];active.update(state='FVG',zone=zone,age=0)
                        event=emit('FVG','FVG',bar,active['id'],reason='连续三根已完成K线形成方向缺口且中间柱方向一致',direction=direction,low=low,high=high,ce=zone['ce'])
                        event['evidence']=[_evidence(x) for x in (a,b,c)]
            elif active and active['state'] in ('FVG','CE_REVIEW'):
                zone=active['zone']
                if active['age']>PARAMETERS['ce_bars']:cancel(bar,'FVG后6根完整K线观察期限结束')
                elif active['state']=='FVG':
                    if bar['low']<=zone['ce']<=bar['high']:
                        _zone_state(zone,'TOUCHED',bar,'后续完整K线触及50% CE'); active['state']='CE_REVIEW'
                        emit('CE','CE_REVIEW',bar,active['id'],reason='形成柱之后的完整K线触及50% CE；仅供历史人工复核',direction=direction,ce=zone['ce'],low=zone['low'],high=zone['high'])
        if not legal or day in seen:
            continue
        for direction,side in [('LONG','low'),('SHORT','high')]:
            crossed=bar['low']<prior[side] if direction=='LONG' else bar['high']>prior[side]
            reclaimed=bar['close']>prior[side] if direction=='LONG' else bar['close']<prior[side]
            if crossed and not reclaimed:
                reason='完整1H收盘未严格收回前日水平；该形成中Sweep候选失效'
                identity=f'{VERSION}|{symbol}|{day}|{direction}|{_iso(bar["end"])}|REJECTED'
                result['sweeps'].append(dict(id=hashlib.sha256(identity.encode()).hexdigest()[:24],kind='SWEEP',state='INVALIDATED',symbol=symbol,timeframe='1H',
                    status='INVALIDATED',direction=direction,level=prior[side],extreme=bar['low'] if direction=='LONG' else bar['high'],
                    occurred_at=_iso(bar['end']),confirmed_at=_iso(bar['known_at']),source=bar['source'],version=VERSION,
                    parameter_version=PARAMETER_VERSION,invalidation_reason=reason,reason=reason,trigger=reason,evidence=[_evidence(bar)]))
        long=bar['low']<prior['low'] and bar['close']>prior['low']
        short=bar['high']>prior['high'] and bar['close']<prior['high']
        if not (long or short):continue
        seen.add(day)
        if active:cancel(bar,'新交易日首个Sweep出现，关闭旧观察链')
        if long and short:
            emit('INVALIDATED','INVALIDATED',bar,f'{day}|AMBIGUOUS',reason='同根双向扫荡并收回，方向不明确')
            continue
        direction='LONG' if long else 'SHORT';level=prior['low'] if long else prior['high'];extreme=bar['low'] if long else bar['high']
        key=f'{day}|{direction}|{level:g}'
        known=[p for p in pivots if p['side']==('high' if long else 'low') and pd.Timestamp(p['known_at'])<=bar['known_at']]
        # 不从缺数据之前的旧结构跨断点建立关联。
        known=[p for p in known if pd.Timestamp(p['occurred_at'])>=history[0]['ts']]
        pivot=known[-1] if known else None
        tr=[max(x['high']-x['low'],abs(x['high']-history[i-1]['close']),abs(x['low']-history[i-1]['close'])) for i,x in enumerate(history[:-1]) if i>0]
        atr=sum(tr[-14:])/14 if len(tr)>=14 else None
        sweep=emit('SWEEP','SWEEP',bar,key,reason='完整1H同柱严格越过前日水平并收盘收回',direction=direction,level=level,extreme=extreme,
                   level_known_at=_iso(prior['known_at']),structure_status='AVAILABLE' if pivot else 'UNKNOWN',atr14=atr)
        if atr is None:
            emit('INVALIDATED','INVALIDATED',bar,key,reason='确认前不足14根完整真实波幅，失效价不可计算',direction=direction)
        else:
            stop=extreme+(-.1*atr if long else .1*atr)
            sweep['invalidation_price']=stop
            active=dict(id=key,direction=direction,state='SWEEP',age=0,pivot=pivot,stop=stop,sweep=sweep['id'])
    result['sweeps'].extend(e.copy() for e in events if e['kind']=='SWEEP')
    result.update(status='AVAILABLE' if any(b['complete'] for b in bars) else 'UNKNOWN',
                  reason=f'历史观察；缺失分桶{gap_count}；供应商最终性未验证',gap_count=gap_count,
                  active_state=active['state'] if active else 'WATCH',active_setup=active['id'] if active else None,
                  completed_bars=sum(b['complete'] for b in bars))
    return result
