"""Read-only projections of real observation artifacts; never fabricate fills."""
import json
import re
import pandas as pd
from .core import SPECS,calendar
from .forward import now


def events_from(path):
    if not path.exists():return []
    events=[]
    lines=path.read_text(encoding='utf-8').splitlines()
    for i,line in enumerate(lines):
        try:events.append(json.loads(line))
        except json.JSONDecodeError:
            if i!=len(lines)-1:raise ValueError('OBSERVATION_LOG_INVALID')
            # Concurrent trailing append is read next refresh.
    return events


def project(root,state,date=None):
    received=now();today=received.tz_convert('America/New_York').strftime('%Y-%m-%d')
    date=date or today
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):raise ValueError('INVALID_SESSION_DATE')
    pd.Timestamp(date)  # Reject impossible dates, no paths from user input.
    folder=root/'artifacts/forward'/date
    events=events_from(folder/'events.jsonl')
    trades=[];markers=[];config=None
    for event in events:
        kind=event['kind'];stamp=event['received_at_utc']
        if kind=='REGISTER':config=event['config']
        if kind=='SIGNAL':
            markers.append(dict(time=event['at'],price=event.get('signal_close',event['or_high'] if event['direction']==1 else event['or_low']),kind='SIGNAL',direction=event['direction'],label='突破确认' if 'signal_close' in event else '突破确认·区间线'))
        if kind=='ENTRY_PROXY':
            pos=event['position'];trade=dict(id=pos['entry_received_at_utc'],product=event.get('product'),contract=event.get('contract'),
                direction=pos['direction'],quantity=event.get('quantity'),entry_time=pos['entry_received_at_utc'],entry_price=pos['entry_price'],
                stop=pos['stop'],target=pos['target'],fee_usd=event.get('fee_usd'),slippage_ticks=event.get('slippage_ticks'),
                status='OPEN',exit_time=None,exit_price=None,net_usd=None,reason=None,execution='SIMULATED_QUOTE_PROXY')
            trades.append(trade);markers.append(dict(time=trade['entry_time'],price=trade['entry_price'],kind='ENTRY',direction=trade['direction'],label='模拟入场',trade_id=trade['id']))
        if kind in ['EXIT_PROXY','POSITION_INVALIDATED']:
            pos=event['position'];trade=next((t for t in trades if t['id']==pos['entry_received_at_utc']),None)
            if trade is not None:
                trade.update(status='COMPLETE' if kind=='EXIT_PROXY' else 'INVALID',exit_time=stamp,exit_price=event.get('exit_price'),net_usd=event.get('net_usd'),reason=event['reason'])
                if kind=='EXIT_PROXY':markers.append(dict(time=stamp,price=event['exit_price'],kind='EXIT',direction=pos['direction'],label='模拟平仓',trade_id=trade['id']))
    bars=[];bar_path=folder/'completed_bars.csv'
    if bar_path.exists():
        frame=pd.read_csv(bar_path)
        if not frame.empty:
            frame=frame[['ts','open','high','low','close','volume']].rename(columns={'ts':'time'})
            bars=json.loads(frame.to_json(orient='records'))
    quotes=[e for e in events if e['kind']=='QUOTE']
    last=quotes[-1] if quotes else None
    stamp=state.get('last_quote_utc') if date==today else None
    stamp=stamp or (last['quote_time_utc'] if last else None)
    price=state.get('last_price') if date==today else None
    price=price if price is not None else (last['last_price'] if last else None)
    age=max(0,(received-pd.Timestamp(stamp)).total_seconds()) if stamp else None
    stale=age is None or age>10 or pd.Timestamp(stamp)>received
    position=state.get('position') if date==today else None
    cfg=state.get('config') or config or {}
    unrealized=None;risk=None
    if position and cfg.get('product') in SPECS:
        point=SPECS[cfg['product']]['point_value']
        risk=abs(position['entry_price']-position['stop'])*point
        if not stale:unrealized=position['direction']*(price-position['entry_price'])*point
    completed=[t for t in trades if t['status']=='COMPLETE']
    net=sum(t['net_usd'] for t in completed)
    cal=calendar(today,today)
    market='CLOSED' if cal.empty else 'PREOPEN' if received<cal.iloc[0].open else 'CLOSED' if received>=cal.iloc[0].close else 'OPEN'
    signal=next((e for e in reversed(events) if e['kind']=='SIGNAL'),None)
    opening=None
    if len(bars)>=10:
        prefix=bars[:10];opening=dict(high=max(b['high'] for b in prefix),low=min(b['low'] for b in prefix))
    dates=sorted(p.name for p in (root/'artifacts/forward').glob('*') if p.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}',p.name))
    choice_file=root/'state/dashboard_choices.json'
    choices=json.loads(choice_file.read_text(encoding='utf-8')) if choice_file.exists() else {}
    report_path=folder/'report.md'
    recommendation=next((line.removeprefix('当日建议：') for line in report_path.read_text(encoding='utf-8').splitlines() if line.startswith('当日建议：')),None) if report_path.exists() else None
    return dict(date=date,today=today,dates=dates,server_time_utc=received.isoformat(),market=market,
        quote=dict(price=price,time=stamp,age_seconds=age,stale=stale,received_time=last.get('received_at_utc') if last else None),
        metrics=dict(entries=len(trades),completed=len(completed),invalid=sum(t['status']=='INVALID' for t in trades),
                     realized_net_usd=net if completed else None,unrealized_gross_usd=unrealized,risk_usd=risk,
                     win_rate=sum(t['net_usd']>0 for t in completed)/len(completed) if completed else None),
        bars=bars,markers=markers,trades=trades,opening=opening,signal=signal,position=position,
        events=[e for e in events if e['kind']!='QUOTE'][-30:],
        latest_choice=choices.get(date,{}).get('option') or next((e.get('option') for e in reversed(events) if e['kind']=='USER_OPTIMIZATION_CHOICE'),None),
        report_available=report_path.exists(),recommendation=recommendation,orders_enabled=False)
