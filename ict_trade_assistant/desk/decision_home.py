"""Decision-first presentation for the local history desk."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .analytics import aggregate_rth
from .daily_update import latest_completed
from .market_state import RULES, market_state
from .plans import risk_reward


def historical_plan(decision):
    structure = (decision or {}).get('structure', {})
    if (not structure.get('linked') or structure.get('stage') not in ('FVG_CONFIRMED', 'CE_REVIEW')
            or not structure.get('region') or not structure.get('invalid')
            or decision['qualification'] >= 2):
        return None
    low, high = structure['region']
    invalid = structure['invalid']
    direction = structure['direction']
    if not ((direction == 'LONG' and 0 < invalid < low <= high)
            or (direction == 'SHORT' and 0 < low <= high < invalid)):
        return None
    return dict(low=low, high=high, invalid=invalid, direction=direction,
                confirmed_at=structure['confirmed_at'], until=structure['until'],
                source=structure['evidence'][-1]['source'], event_id=structure['event_id'],
                invalid_confirmed_at=structure['evidence'][0]['confirmed_at'],
                invalid_event_id=structure['evidence'][0]['id'])


def manual_prices(plan):
    rr = risk_reward(plan)
    if rr is None:
        return None
    long = plan['direction'] == 'LONG'
    entry = plan['high'] if long else plan['low']
    first, second = (plan['target_low'], plan['target_high']) if long else (plan['target_high'], plan['target_low'])
    risk = abs(entry - plan['invalid'])
    return dict(entry=entry, risk=risk, target1=first, target2=second,
                reward1=abs(first-entry), reward2=abs(second-entry),
                rr1=rr, rr2=abs(second-entry)/risk)


def _price(value):
    return f'{value:.6f}'.rstrip('0').rstrip('.')


def _level(fig, x, name, value, color, source):
    fig.add_scatter(x=x, y=[value]*2, mode='lines', name=name,
                    line=dict(color=color, width=2, dash='dot'),
                    hovertemplate=name+' %{y:.6f}<extra>'+source+'</extra>')


@st.cache_data(max_entries=96, show_spinner=False)
def _analysis(frame, period, asof, source):
    if period == '1H' and not frame.empty:
        frame = aggregate_rth(frame, 60, asof)
    return market_state(frame, period, asof, source)


def _daily_source(data):
    if data.get('history_origin'):
        return '富途原生日K归档'
    meta = data.get('coverage') or data.get('health', {})
    return '/'.join(str(meta[k]) for k in ('source', 'feed') if meta.get(k)) or 'UNKNOWN'


def _pick_history(pick, code, key):
    pick(code, key)
    st.session_state['decision_view'] = '历史时点回顾'


def render_home(selected, data, plan, decision, rows, decisions, replay_asof, wall_asof, pick):
    d = data[selected]
    st.title('ICT 交易工作台')
    st.subheader(f'{selected[3:]} · 市场摘要')
    replay = st.radio('分析视角', ['最新归档日K', '历史时点回顾'], horizontal=True, key='decision_view')
    historical = replay == '历史时点回顾'
    asof = replay_asof if historical else wall_asof
    period = '1H' if historical and not d['minute'].empty else '1D'
    frame, source = (d['minute'], '富途分钟归档 → 纽约RTH 1H') if period == '1H' else (d['daily'], _daily_source(d))
    if period == '1D' and d.get('independent_coverage'):
        meta = d['independent_coverage']
        source_choice = st.radio('日K来源（分开计算）', ['原历史档案', '独立更新档案'], horizontal=True)
        if source_choice == '独立更新档案':
            frame, source = d['independent_daily'], f"{meta['source']}/{meta['feed']} · {meta['adjustment']}"
            st.caption('独立档案的供应商聚合时段等价性未验证。')
    state, chart = _analysis(frame, period, asof, source)
    latest_state, _ = _analysis(d['daily'], '1D', wall_asof, _daily_source(d))
    latest_date = latest_state['at'].date().isoformat() if latest_state['at'] is not None else None
    expected = latest_completed(wall_asof)
    freshness = '无可用日K' if latest_date is None else '行情已过期' if latest_date < expected else '日K截至最近完成交易日'
    st.write(f"**{'历史趋势可描述' if state['trend'] != 'UNKNOWN' else '方向无法判断'}** · {period} · "
             f"**{state['trend']}** · 波动 **{state['volatility']}**")
    st.error('DATA_BLOCKED · 实时交易审查关闭 · 暂无合格买卖点')
    st.caption(f"分析时点（analysis_asof）{asof:%Y-%m-%d %H:%M %Z} · 最近有效分析柱结束 {state['at'] or '—'} · {source}")
    st.caption(f"最新原归档日K收盘 {latest_state['at'] or '—'} · "
               f"{_price(latest_state['close']) if latest_state['close'] is not None else '—'} · "
               f"最近完成纽约交易日 {expected} · {freshness} · 仅历史资料")
    if d.get('independent_coverage'):
        meta = d['independent_coverage']
        updated, _ = _analysis(d['independent_daily'], '1D', wall_asof, f"{meta['source']}/{meta['feed']}")
        if updated['at'] is not None:
            status = '已过期' if updated['at'].date().isoformat() < expected else '截至最近完成交易日'
            st.caption(f"最新独立归档日K收盘 {updated['at']} · {_price(updated['close'])} · {status} · {updated['source']}")
    if st.session_state.get('_daily_update_status') == 'BLOCKED':
        st.warning('每日自动更新 BLOCKED · 未验证本地无人值守数据访问')
    if historical:
        st.caption('按行情发生时点截断。当前归档可能于回顾时点之后取得。')
    if d.get('daily_only'):
        st.caption('仅日K · 1H ICT 资格不足')

    setup = historical_plan(decision)
    manual = manual_prices(plan)
    st.write('**当前候选方向／入场区／止损／目标** · — ／ — ／ — ／ —')
    st.caption('下一步：等待实时资格验收及新的合格结构。历史区域和人工计划可在下方单独复核。')
    st.subheader('Top5 观察候选')
    st.caption('当前合格观察：0 只。排名仅代表观察优先级。')
    with st.expander(f'仅供历史研究 · {len(rows[:5])} 只'):
        for row in rows[:5]:
            code = row['symbol']
            hist = historical_plan(row['decision'])
            candidate = f"{_price(hist['low'])}–{_price(hist['high'])}" if hist else '暂无合格入场区'
            if st.button(f"{code[3:]} · {row['direction']} · 历史复核", key='home_'+code,
                         on_click=_pick_history, args=(pick, code, row['key'])):
                st.rerun()
            trend, _ = _analysis(data[code]['daily'], '1D', replay_asof, _daily_source(data[code]))
            expiry = '历史观察期限已过' if pd.Timestamp(row['valid_until']) < wall_asof else '仅历史复核'
            st.caption(f"日K趋势 {trend['trend']} · {candidate} · {expiry} · 历史观察距离 "
                       f"${row['gap']:.2f}（{row['distance_basis']}） · {row['quote_at']} · 下一步：复核历史证据")
    blocked = [r['symbol'][3:] for r in decisions if r['qualification'] >= 2]
    with st.expander(f'历史候选资格不足或被阻断 · {len(blocked)} 只'):
        st.write('、'.join(blocked) or '—')

    st.subheader(f'{selected[3:]} · {period} 主K线')
    manual_layer = bool(manual and not historical and st.checkbox('叠加用户计划价格（待人工复核）'))
    if chart.empty:
        st.info('该时点无可用K线')
    else:
        dates = chart.ts.map(str)
        fig = go.Figure(go.Candlestick(x=dates, open=chart.open, high=chart.high,
                                        low=chart.low, close=chart.close, name=period))
        x = [dates.iloc[0], dates.iloc[-1]]
        if manual_layer:
            origin = f"用户计划 v{plan['version']} · 保存 {plan['updated_at']} · 周期未指定"
            _level(fig, x, '人工计划入场下沿', plan['low'], '#ffbd66', origin)
            if plan['high'] != plan['low']:
                _level(fig, x, '人工计划入场上沿', plan['high'], '#ffbd66', origin)
            _level(fig, x, '人工计划失效／止损参考', plan['invalid'], '#fa7885', origin)
            _level(fig, x, '人工计划目标一', manual['target1'], '#60d4ab', origin)
            if manual['target2'] != manual['target1']:
                _level(fig, x, '人工计划目标二', manual['target2'], '#77aafd', origin)
        if historical and period == '1H' and setup:
            origin = str(setup['confirmed_at'])
            _level(fig, x, '历史入场下沿', setup['low'], '#ffbd66', origin)
            if setup['high'] != setup['low']:
                _level(fig, x, '历史入场上沿', setup['high'], '#ffbd66', origin)
            _level(fig, x, '历史结构失效／止损参考', setup['invalid'], '#fa7885', str(setup['invalid_confirmed_at']))
        fig.update_layout(template='plotly_dark', height=430, showlegend=True,
                          xaxis_rangeslider_visible=False, yaxis_side='right',
                          legend=dict(orientation='h'), margin=dict(l=8,r=12,t=12,b=24),
                          uirevision=f'{selected}-{period}-{source}')
        st.plotly_chart(fig, width='stretch', key='decision_main_chart')
    st.subheader(f'{selected[3:]} · 交易决策卡')
    st.write(f"**DATA_BLOCKED** · 市场方向 {state['trend']} · 暂无合格买卖点")
    if setup:
        st.write(f"**系统历史条件化计划（1H）** · {setup['direction']} · "
                 f"入场区 {_price(setup['low'])}–{_price(setup['high'])} · "
                 f"结构失效／止损参考 {_price(setup['invalid'])}")
        st.caption(f"仅在回顾时点复核 · {setup['source']} · 确认 {setup['confirmed_at']} · 历史期限 {setup['until']} · {setup['event_id']}")
        st.caption(f"失效价来源：Sweep {setup['invalid_event_id']} · 确认 {setup['invalid_confirmed_at']}")
        st.caption(f"目标一／二、毛R/R — · 下一条件 {decision['next_condition']} · 失效 {decision['invalid_condition']}")
    elif decision and decision['historical_stage'] == 'INVALIDATED':
        st.caption('历史结构已失效 · 等待新的合格结构。')
    if manual:
        memo = plan.get('memo') or ''
        purpose = '测试用途 · ' if '测试' in memo or 'test' in (memo+' '+plan['strategy_version']).lower() else ''
        st.write(f"**{purpose}用户人工计划（待人工复核）** · {plan['direction']} · 入场区 "
                 f"{_price(plan['low'])}–{_price(plan['high'])} · 人工失效／止损参考 {_price(plan['invalid'])} · "
                 f"目标一／二 {_price(manual['target1'])} ／ {_price(manual['target2'])}")
        st.caption(f"计划第 {plan['version']} 版 · 保存 {plan['updated_at']} · 周期未在计划中指定 · "
                   "等待用户确认用途、价格与条件。到达人工失效价时重新复核计划。")
        st.caption(f"毛R/R {manual['rr1']:.2f} / {manual['rr2']:.2f} · 保守入场 "
                   f"{_price(manual['entry'])} · 风险 {_price(manual['risk'])} · "
                   f"毛收益 {_price(manual['reward1'])} / {_price(manual['reward2'])}")
        if historical and pd.Timestamp(plan['updated_at']) > asof:
            st.caption('计划保存晚于回顾时点，单独展示。')
        if memo:
            st.text(memo)
    with st.expander('市场计算与价格证据'):
        st.caption(RULES)
        st.write({key: str(value) for key, value in state.items()})
        st.caption('人工计划毛R/R以失效价作为止损参考，采用保守区间边界，未计成本或滑点。')
        if manual:
            st.write(manual)
