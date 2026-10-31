"""人工计划价格校验和保守风险回报；不生成自动策略信号。"""
import math


def validate_plan(p):
    import re
    if not re.fullmatch(r'US\.[A-Z][A-Z0-9.-]{0,14}',p.get('symbol','')) or p['symbol']=='US.VIX':
        raise ValueError('请选择普通美股或 ETF 标的，VIX 只作风险背景。')
    if p.get('direction') not in ('LONG','SHORT') or not p.get('strategy_version','').strip():
        raise ValueError('必须设置方向及策略版本。')
    nums=[p.get(k) for k in ('low','high','invalid','target_low','target_high')]
    if any(not isinstance(n,(int,float)) or not math.isfinite(n) or n<=0 for n in nums):
        raise ValueError('入场、失效及目标必须是有限正数。')
    low,high,invalid,tl,th=nums
    if low>high or tl>th:
        raise ValueError('价格区间下限不能高于上限。')
    if p['direction']=='LONG' and not invalid<low<=high<tl:
        raise ValueError('做多须满足：失效价 < 入场区 ≤ 目标区。')
    if p['direction']=='SHORT' and not th<low<=high<invalid:
        raise ValueError('做空须满足：目标区 < 入场区 < 失效价。')


def risk_reward(p):
    if not p or p.get('status')!='ACTIVE': return None
    try: validate_plan(p)
    except (ValueError,KeyError,TypeError): return None
    if p['direction']=='LONG':
        entry=p['high']; risk=entry-p['invalid']; reward=p['target_low']-entry
    else:
        entry=p['low']; risk=p['invalid']-entry; reward=entry-p['target_high']
    return reward/risk


def active_plan(store,symbol):
    return next((p for p in store.plans(symbol) if p['status']=='ACTIVE'),None)


def evaluate_plan(store,p,health,day,distance_bps):
    from .analytics import observe
    if not p or p['status']!='ACTIVE': return
    state,reason=observe(health.get('price'),health['quality'],p,distance_bps)
    if state not in ['接近流动性区域','价格到达关注区域','失效']: return
    store.event('PLAN_ALERT',p['symbol'],'人工计划价格提醒：'+reason,
        dict(plan_id=p['plan_id'],plan_version=p['version'],zone=p,health=health),
        f"plan_alert:{p['plan_id']}:{p['version']}:{day}:{state}",
        plan_guard=(p['plan_id'],p['version']))
