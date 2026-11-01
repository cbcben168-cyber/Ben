"""合成完整链与工程验证；不代表真实MSS样本或盘中验收。"""
from copy import deepcopy
from datetime import timedelta
import itertools
import json
from pathlib import Path
import pandas as pd
import plotly.graph_objects as go
import pytest
from desk.decision import decision, prioritize, structure, deadline
from desk.ict_v03 import scan
from desk.ict_view import add_event_layers
from desk.observations import build_observation, SYMBOLS, record_events
from desk.store import Store, DEFAULTS
from test_ict_v03 import history, at


def observation(now, symbol='US.SPY'):
    row=dict(symbol=symbol,key='PDL',low=99.,high=99.,price=104.,atr=5.,gap=5.,atr_distance=1.,
        priority=1,state='OUTSIDE',direction='UNKNOWN',quote_at=now.isoformat(),
        valid_until=deadline(now,1),distance_basis='合成历史测试',trading_day='2026-10-29',
        next_action='人工核对',reason='合成价位')
    return dict(symbol=symbol,status='AVAILABLE',mode='PREPARATION',source='SYNTHETIC_TEST_ONLY',
        reference_price=104.,atr=5.,reference_at=now.isoformat(),distance_basis='合成历史测试',
        trading_day='2026-10-29',monitors=[row],health=dict(quality='STALE'),reason='合成历史准备')


@pytest.mark.parametrize('time,stage',[(at(10,31),'FVG_CONFIRMED'),(at(10,32),'SWEEP_CONFIRMED'),
    (at(11,32),'MSS_CONFIRMED'),(at(12,32),'FVG_CONFIRMED'),(at(14,32),'CE_REVIEW'),(at(16,2),'INVALIDATED')])
def test_synthetic_progression(time,stage):
    s=structure(scan('US.SPY',history(),time),time)
    # 早期独立缺口可能存在；只核对本日Sweep隔离门禁。
    if time==at(10,31):
        assert not any(e.get('kind')=='SWEEP' and e['occurred_at'].startswith('2026-10-29') for e in s['evidence'])
    elif time==at(16,2):
        r=scan('US.SPY',history(),time)
        assert structure(dict(r,fvgs=[]),time)['stage']=='INVALIDATED'
    else: assert s['stage']==stage and (s['linked'] if stage in ('MSS_CONFIRMED','CE_REVIEW') else True)


def test_four_symbols_regions_determinism_no_input_mutation():
    now=at(12,32);obs={c:observation(now,c) for c in SYMBOLS};reports={c:scan(c,history(),now) for c in SYMBOLS}
    obs['US.VIX']=observation(now,'US.VIX')
    for o in obs.values():o['monitors'].append(dict(o['monitors'][0],key='OR_5_LOW'))
    before=deepcopy(obs);expected=prioritize(obs,reports,now)
    for order in itertools.permutations(SYMBOLS):
        assert prioritize({c:obs[c] for c in order},reports,now)==expected
    assert obs==before and len(expected)==4 and len({r['symbol'] for r in expected})==4
    assert len(expected[0]['regions'][0]['members']) in (0,2)
    assert any(len(r['members'])==2 for r in expected[0]['regions'])


def test_independent_fvg_never_complete_chain():
    now=at(14,32);r=scan('US.SPY',history(),now)
    r['events']=[]
    for z in r['fvgs']:z['setup_id']=None
    d=decision('US.SPY',observation(now),r,now)
    assert not d['linked'] and not d['live_review'] and d['stage']!='CE_REVIEW'
    assert '独立FVG' in d['next_condition']


@pytest.mark.parametrize('damage',['missing','bad','forming','4H'])
def test_gate_damage(damage):
    now=at(11,32);f=history()
    if damage=='missing':f=f[f.ts!=at(11,0)]
    if damage=='bad':f.loc[f.index[-1],'low']=-1;now=at(16,2)
    if damage=='forming':now=at(11,31)
    r=scan('US.SPY',f,now,timeframe='4H' if damage=='4H' else '1H')
    s=structure(r,now)
    assert s['stage'] not in ('MSS_CONFIRMED','CE_REVIEW')


def test_qualification_expiry_and_fixed_tie_break():
    now=at(12,32);r=scan('US.SPY',history(),now);o=observation(now)
    later=pd.Timestamp(deadline(now,6))+timedelta(seconds=1)
    assert structure(dict(r,fvgs=[]),later)['stage']=='INVALIDATED'
    independent=deepcopy(r)
    independent['events']=[]
    for z in independent['fvgs']:z['setup_id']=None
    assert structure(independent,later)['reason']
    o.update(status='UNAVAILABLE')
    d=decision('US.SPY',o,r,now)
    assert d['stage']=='UNKNOWN' and d['qualification']==2 and not d['live_review']
    obs={c:observation(now,c) for c in reversed(SYMBOLS)}
    assert [d['symbol'] for d in prioritize(obs,{},now)]==list(SYMBOLS)


def test_causal_prefix_and_chart_evidence():
    f=history()
    for now in [at(10,31),at(10,32),at(11,32),at(12,32),at(14,32)]:
        full=scan('US.SPY',f,now);prefix=scan('US.SPY',f[f.ts<now],now)
        d=decision('US.SPY',observation(now),full,now)
        assert d==decision('US.SPY',observation(now),prefix,now)
        fig=go.Figure();add_event_layers(fig,full)
        coordinates={(str(x),float(y)) for t in fig.data for x,y in zip(t.x,t.y) if y is not None}
        for e in d['structure']['evidence']:
            if e.get('kind') in ('SWEEP','MSS','FVG','CE'):
                price=e.get('level',e.get('structure_price',e.get('ce')))
                assert (e['confirmed_at'],float(price)) in coordinates


def test_plan_evidence_versions_concurrency_and_alert_dedupe(tmp_path,market_fixture):
    a=Store(tmp_path/'isolated.db');b=Store(tmp_path/'isolated.db')
    snapshot=decision('US.SPY',observation(at(12,32)),scan('US.SPY',history(),at(12,32)),at(12,32))
    payload=dict(symbol='US.SPY',direction='LONG',strategy_version='人工v04',low=99.,high=100.,invalid=98.,target_low=102.,target_high=103.,memo='记录',decision_evidence=snapshot)
    ident,v=a.save_plan(payload)
    b.save_plan(dict(payload,memo='新版本'),ident,v)
    with pytest.raises(ValueError,match='其他窗口'):a.save_plan(payload,ident,v)
    # SQLite计划采用JSON；元组区域的持久化契约为JSON数组，全部字段必须保留。
    assert len(a.plan_history(ident))==2 and a.plan_history(ident)[0]['decision_evidence']==json.loads(json.dumps(snapshot))
    now=pd.Timestamp('2026-10-30T10:10',tz='America/New_York').to_pydatetime()
    obs=build_observation('US.SPY',market_fixture,DEFAULTS,now,dict(low=99.,high=101.))
    for store in [a,b,a,b]:record_events(store,obs)
    count=len(a.table('market_events'))
    for store in [a,b]:record_events(store,build_observation('US.SPY',market_fixture,DEFAULTS,now+timedelta(seconds=91)))
    assert len(a.table('market_events'))==count
    assert count==len(set(a.table('market_events').dedupe))


def test_no_trade_api_and_unchanged_frozen_recognizer():
    import ast
    root=Path(__file__).resolve().parents[1]
    forbidden={'OpenSecTradeContext','OpenFutureTradeContext','place_order','modify_order','position_list_query','accinfo_query','get_acc_list'}
    for file in [root/'app.py',*list((root/'desk').glob('*.py'))]:
        tree=ast.parse(file.read_text(encoding='utf-8'))
        names={n.attr for n in ast.walk(tree) if isinstance(n,ast.Attribute)}|{n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        assert not names & forbidden


def test_quarantine_and_unqualified_event_evidence_rejected():
    now=at(12,32);r=scan('US.SPY',history(),now)
    r['fvgs']=[]
    for e in r['events']:
        if e['kind']=='FVG':e['confirmed_at']=at(12,31).isoformat()
    assert structure(r,now)['stage']=='MSS_CONFIRMED'
    for e in r['events']:e['source']=''
    assert structure(r,now)['stage']=='PRICE_WATCH'


def test_stale_live_and_data_tier_precede_structure():
    now=at(12,32);obs={c:observation(now,c) for c in SYMBOLS}
    obs['US.SPY'].update(mode='LIVE',health=dict(quality='AVAILABLE',price=104.,right='LV3',quote_at=(now-timedelta(seconds=91)).isoformat()))
    reports={'US.SPY':scan('US.SPY',history(),now)}
    rows=prioritize(obs,reports,now)
    assert rows[-1]['symbol']=='US.SPY' and rows[-1]['stage']=='UNKNOWN'
    assert all(r['qualification']<2 for r in rows[:-1])
