"""Decision-first presentation for the local history desk."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .analytics import aggregate_rth
from .daily_update import latest_completed
from .market_state import RULES, market_state
from .plans import risk_reward
from .dashboard_cards import CSS, summary, action, candidate


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
    st.markdown(CSS, unsafe_allow_html=True)
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
    setup = historical_plan(decision)
    manual = manual_prices(plan)
    missing = state['at'] is None
    stale = latest_date is not None and latest_date < expected
    at_text = state['at'].strftime('%Y-%m-%d %H:%M 纽约') if state['at'] is not None else '暂无有效行情'
    summary(selected[3:], state, stale, missing, at_text, historical)
    left, right = st.columns([1.7, 1], gap='medium')
    with left:
        with st.container(key='answer-chart'):
            st.subheader(f'{selected[3:]} · 主图')
            st.caption(('日K' if period == '1D' else '1小时') + ' · 历史收盘资料')
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
                fig.update_layout(template='plotly_dark', height=400, showlegend=True,
                                  xaxis_rangeslider_visible=False, yaxis=dict(side='right', automargin=True),
                                  legend=dict(orientation='h'), margin=dict(l=8,r=50,t=12,b=24),
                                  uirevision=f'{selected}-{period}-{source}')
                st.plotly_chart(fig, width='stretch', key='decision_main_chart')
    with right:
        with st.container(key='answer-action'):
            action(selected[3:], manual, plan, setup if historical else None, stale)
    st.subheader('Top5 · 观察名单')
    st.caption('当前暂无合格买卖点 · 以下仅为观察顺序')
    watch = decisions[:5]
    if not watch:
        st.info('暂无观察候选')
    for col, item in zip(st.columns(max(len(watch), 1)), watch):
        code = item['symbol']
        with col:
            candidate(code[3:], '等待新行情', '暂无合格买卖点', '更新后复核')
            if st.button('查看 '+code[3:], key='watch_'+code, on_click=pick, args=(code, None), width='stretch'):
                st.rerun()
            with st.expander('详情'):
                st.caption('仅日K，1小时条件尚不具备' if data[code].get('daily_only') else '以前的重要价格位置可在历史证据中复核')
    with st.expander('专业分析和计算依据'):
        st.caption(f'分析时点 {asof.isoformat()} · 周期 {period} · {source}')
        st.caption(f'最新原归档日K收盘 {latest_state["at"] or "暂无"} · 最近完成纽约交易日 {expected} · {freshness}')
        if d.get('independent_coverage'):
            st.write('独立更新档案', d['independent_coverage'])
        st.caption(RULES)
        st.write({key: str(value) for key, value in state.items()})
        if manual:
            st.write('用户计划计算依据', manual)
            st.caption(f'计划第 {plan["version"]} 版 · 保存 {plan["updated_at"]} · 周期未指定')
            st.text(plan.get('memo') or '未填写备注')
            if historical and pd.Timestamp(plan['updated_at']) > asof:
                st.caption('计划保存晚于回顾时点，单独展示。')
    with st.expander('历史结构证据与原始时间'):
        for row in rows[:5]:
            code = row['symbol']
            if st.button(code[3:]+' · 历史复核', key='home_'+code,
                         on_click=_pick_history, args=(pick, code, row['key'])):
                st.rerun()
            st.caption('以前的重要价格位置 · '+str(row['quote_at'])+' · 历史期限 '+str(row['valid_until']))
        if setup:
            st.write('历史条件化计划', setup)
        st.caption('历史观察与当前交易资格分别检查。')
    with st.expander('数据更新与资格详情'):
        st.caption('实时ICT资格继续关闭 · DATA_BLOCKED')
        st.caption('每日自动更新 BLOCKED · 未验证本地无人值守数据访问' if st.session_state.get('_daily_update_status') == 'BLOCKED' else '每日更新状态见设置与审计')
        if d.get('daily_only'):
            st.caption('只有日K，1小时ICT资格不足')
