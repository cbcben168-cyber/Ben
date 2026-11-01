"""v0.4 确定性历史决策辅助；复用冻结识别器，不推导入场或订单。"""
from datetime import timedelta
import math
import pandas as pd
from .clock import CAL, bounds
from .observations import SYMBOLS, regions, live_health
from .ict_live_gate import ict_live_qualification

VERSION = 'ICT-DECISION-v0.4'
LABELS = dict(PRICE_WATCH='价格观察', SWEEP_CONFIRMED='扫荡已确认',
              MSS_CONFIRMED='结构突破已确认', FVG_CONFIRMED='缺口已确认',
              CE_REVIEW='中点人工复核', INVALIDATED='已失效', UNKNOWN='未知／数据阻断')
ORDER = {s: i for i, s in enumerate(['CE_REVIEW','FVG_CONFIRMED','MSS_CONFIRMED',
                                    'SWEEP_CONFIRMED','UNLINKED_WATCH','PRICE_WATCH','INVALIDATED','UNKNOWN'])}


def structure_priority(value):
    return ORDER['UNLINKED_WATCH'] if value['stage']=='FVG_CONFIRMED' and not value['linked'] else ORDER[value['stage']]


def deadline(confirmed, bars):
    """交易日历中的后续1H收盘加2分钟；包含每日尾部30分钟柱。"""
    t = pd.Timestamp(confirmed)
    count = 0
    for day in CAL.sessions_in_range(str(t.date()), str((t + timedelta(days=35)).date())):
        start, end = bounds(day.date())
        while start < end:
            start = min(start + timedelta(hours=1), end)
            known = start + timedelta(minutes=2)
            if known > t:
                count += 1
                if count == bars:
                    return known.isoformat()
    raise ValueError('观察期限超出日历范围')


def _known(item, now):
    try:
        t = pd.Timestamp(item['confirmed_at'])
        if t.tzinfo is None or t > now or item.get('source') in (None,'','UNKNOWN','UNAVAILABLE') or not item.get('evidence'):
            return False
        return all(pd.Timestamp(b['end'])+timedelta(minutes=2)<=t and pd.Timestamp(b['known_at'])<=t
                   for b in item['evidence'])
    except (KeyError, TypeError, ValueError):
        return False


def structure(report, now):
    """只从同setup、同方向且按时间确认的事件建立链，独立FVG单独保留。"""
    base = dict(stage='UNKNOWN', linked=False, evidence=[], missing=[], until=None,
                invalid=None, region=None, event_id=None, confirmed_at=None, direction='UNKNOWN')
    if report.get('status') != 'AVAILABLE' or report.get('timeframe') != '1H':
        return dict(base, missing=[report.get('reason') or '1H历史证据不可用'])
    events = sorted([e for e in report['events'] if e['status']=='CONFIRMED' and _known(e,now)],
                    key=lambda e: (pd.Timestamp(e['confirmed_at']), report['events'].index(e)))
    choices = []
    for setup in sorted({e['setup_id'] for e in events if e['kind']=='SWEEP'}):
        chain = [e for e in events if e['setup_id']==setup and e['kind']!='WATCH']
        sweep = next(e for e in chain if e['kind']=='SWEEP')
        accepted = [sweep]; expected = ['MSS','FVG','CE']; invalidated = None
        for e in chain[chain.index(sweep)+1:]:
            if e['kind']=='INVALIDATED':
                invalidated=e; break
            if expected and e['kind']==expected[0] and e['direction']==sweep['direction']:
                if e['kind']=='MSS' and e.get('associated_sweep')!=sweep['id']:
                    continue
                prior=pd.Timestamp(accepted[-1]['confirmed_at']);current=pd.Timestamp(e['confirmed_at'])
                if current >= prior and (e['kind']=='FVG' or current>prior):
                    accepted.append(e); expected.pop(0)
        latest=accepted[-1]; kind=latest['kind']
        anchor = next((e for e in reversed(accepted) if e['kind']=='FVG'),latest)
        # 冻结规则：MSS含当根共6柱；Sweep/FVG各允许后续4/6柱。
        until=deadline(anchor['confirmed_at'], {'SWEEP':4,'MSS':5,'FVG':6,'CE':6}[anchor['kind']])
        expired = now > pd.Timestamp(until)
        stage='INVALIDATED' if invalidated or expired else dict(SWEEP='SWEEP_CONFIRMED',MSS='MSS_CONFIRMED',FVG='FVG_CONFIRMED',CE='CE_REVIEW')[kind]
        choices.append(dict(base, stage=stage,linked=kind in ('MSS','FVG','CE'),
            evidence=accepted+([invalidated] if invalidated else []),until=until,
            invalid=sweep.get('invalidation_price'),region=(latest['low'],latest['high']) if 'low' in latest else (latest.get('structure_price',sweep['level']),)*2,
            event_id=(invalidated or latest)['id'],confirmed_at=(invalidated or latest)['confirmed_at'],direction=sweep['direction'],
            missing=['缺少Sweep确认时已知的固定Pivot'] if sweep.get('structure_status')=='UNKNOWN' else [],
            reason=invalidated['reason'] if invalidated else '观察期限结束；等待重新计算' if expired else latest['reason']))
    for z in report.get('fvgs',[]):
        if z.get('setup_id') or not _known(z,now):
            continue
        until=deadline(z['confirmed_at'],6)
        invalid=z['status']=='INVALIDATED' or now>pd.Timestamp(until)
        choices.append(dict(base,stage='INVALIDATED' if invalid else 'FVG_CONFIRMED',
            evidence=[z],until=until,region=(z['low'],z['high']),event_id=z['id'],
            confirmed_at=z['confirmed_at'],direction=z['direction'],
            missing=['独立FVG缺少关联Sweep与MSS；不得进入完整链或CE复核'],
            reason=(z.get('invalidation_reason') or '观察期限结束；等待重新计算') if invalid else '独立FVG，仅作缺口观察'))
    if not choices:
        return dict(base,stage='PRICE_WATCH',missing=['尚无已确认Sweep／MSS链'])
    return min(choices,key=lambda x:(structure_priority(x),not x['linked'],-pd.Timestamp(x['confirmed_at']).timestamp(),x['event_id']))


def decision(symbol, observation, report, now):
    now=pd.Timestamp(now)
    s=structure(report,now)
    areas=regions(observation)
    price=observation.get('reference_price');atr=observation.get('atr')
    qualified=observation.get('status')=='AVAILABLE' and observation.get('source') not in (None,'','UNKNOWN','UNAVAILABLE')
    qualified=qualified and all(isinstance(x,(int,float)) and math.isfinite(x) and x>0 for x in (price,atr))
    live=observation.get('mode')=='LIVE' and live_health(observation['health'],now.to_pydatetime())['quality']=='AVAILABLE'
    if observation.get('mode')=='LIVE' and not live:
        qualified=False
    tier=0 if qualified and live else 1 if qualified else 2
    # 历史结构可以展示，但无合格价格数据不推进SOP。
    stage=s['stage'] if qualified else 'UNKNOWN'
    ict_qualification=ict_live_qualification(report,s,now)
    live_review=bool(live and stage=='CE_REVIEW' and s['linked'] and ict_qualification['qualified'])
    if s['region'] and qualified and s['stage']!='INVALIDATED':
        low,high=s['region'];gap=max(low-price,price-high,0)
        areas=areas+[dict(symbol=symbol,key=s['event_id'],region_label='历史结构区域',low=low,high=high,
            gap=gap,atr_distance=gap/atr,priority=0,keys=[s['event_id']],members=[],state='INSIDE' if gap==0 else 'OUTSIDE',
            direction=s['direction'],quote_at=observation['reference_at'],valid_until=s['until'],
            distance_basis=observation['distance_basis'],next_action='核对历史结构与下一条件',
            reason=s.get('reason','历史结构'),trading_day=observation['trading_day'])]
    areas=sorted(areas,key=lambda r:(r['atr_distance'],-len(set(r.get('keys',[r['key']]))),r['priority'],r['key']))
    focus=next((r for r in areas if s['event_id']==r['key']),areas[0] if areas else None)
    missing=list(s['missing'])
    if not qualified:missing.append(observation.get('reason','价格或ATR来源资格不足'))
    if not live:missing.append('当前不具备实时审查资格；仅供历史准备')
    if not ict_qualification['qualified']:missing.append(ict_qualification['reason'])
    next_condition=dict(PRICE_WATCH='等待完整1H扫荡并收盘收回流动性水平',SWEEP_CONFIRMED='等待固定且事前已知Pivot的1H收盘突破（MSS）',
        MSS_CONFIRMED='等待同观察链、同方向的关联FVG确认',FVG_CONFIRMED='等待形成柱之后完整K线触及CE' if s['linked'] else '先等待合格Sweep与MSS关联；独立FVG不推进完整链',
        CE_REVIEW='人工审查风险、价格、数据时效与执行条件' if live_review else '仅作历史CE人工观察；等待ICT结构独立实时确认、实际到达时间及RTH验收',INVALIDATED='关闭旧观察链，等待新的合格条件',UNKNOWN='补齐合格来源、价格、ATR及完整1H证据')[stage]
    confirmed=[dict(id=e['id'],kind=e.get('kind','FVG'),occurred_at=e.get('occurred_at'),confirmed_at=e['confirmed_at'],source=e['source'],evidence=e['evidence']) for e in s['evidence']]
    return dict(symbol=symbol,version=VERSION,stage=stage,historical_stage=s['stage'],linked=s['linked'],
        stage_label='未关联缺口观察' if stage=='FVG_CONFIRMED' and not s['linked'] else LABELS[stage],
        price_live_qualified=live,ict_live_qualification=ict_qualification,
        qualification=tier,focus=focus,regions=areas,structure=s,evidence=confirmed,missing=missing,
        next_condition=next_condition,next_region=None if s['stage']=='INVALIDATED' else s['region'] or ((focus['low'],focus['high']) if focus else None),
        until=s['until'] or (focus.get('valid_until') if focus else None),invalid=s['invalid'],
        invalid_condition=s.get('reason') if stage=='INVALIDATED' else '已完成K线触及Sweep失效价、缺分钟、越过FVG远端或观察期限结束',
        allowed=['记录备注','维护人工计划并保存证据版本']+(['人工风险与执行审查'] if live_review else []),
        forbidden=['自动确认入场','自动计算下单数量','账户或持仓接口查询','自动下单','未完成K线推进','ICT实时自动提醒'],
        live_review=live_review)


def prioritize(observations, reports, now):
    rows=[decision(c,observations[c],reports.get(c,{}),now) for c in SYMBOLS if c in observations]
    return sorted(rows,key=lambda d:(d['qualification'],structure_priority(d),
        not d['linked'] if d['stage']=='FVG_CONFIRMED' else False,
        d['focus']['atr_distance'] if d['focus'] else float('inf'),
        -len(set(d['focus'].get('keys',[]))) if d['focus'] else 0,
        -pd.Timestamp(d['structure']['confirmed_at']).timestamp() if d['structure']['confirmed_at'] else 0,
        SYMBOLS.index(d['symbol'])))
