"""Decision-first presentation for the local history desk."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .analytics import aggregate_rth
from .daily_update import latest_completed
from .market_state import RULES, market_state
from .plans import risk_reward
from .dashboard_cards import CSS, summary, action, candidate
from .experiment import BASELINE, completed_snapshot, distance_result
from .experiment_ui import controls, comparison_view
from .ema_layers import LAYER_MODES, UNAVAILABLE, ema_points, add_ema_lines
from .futu_daily import FUTU, CONTRACT, PRICE_NOTE, PLAN_NOTE, select_history
from .futu_hourly import CONTRACT as HOURLY, MISSING, hourly_prefix
from .historical_prices import references, target_readiness, focus_symbols, nearest_reference


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
def _analysis(frame, period, asof, source, config=BASELINE):
    if period == '1H' and not frame.empty:
        if source == HOURLY:
            frame = hourly_prefix(frame, asof)
        else:
            frame = frame.loc[frame.eligible.eq(True) & (frame.ts + pd.Timedelta(minutes=3) <= asof)]
            frame = aggregate_rth(frame, 60, asof)
    return market_state(frame, period, asof, source, config)


@st.cache_data(max_entries=96, show_spinner=False)
def _distance(data, state, config, period):
    return distance_result(data, state, config, period)


@st.cache_data(max_entries=128, show_spinner=False)
def _ema_points(frame, period, asof, source, config):
    return ema_points(frame, period, asof, source, config)


@st.cache_data(max_entries=48, show_spinner=False)
def _replay_decision(selected, data, asof):
    from .decision import decision
    from .observations import build_observation
    from .ict_v03 import scan
    snapshot = completed_snapshot(data, asof)
    observation = build_observation(selected, snapshot, {'zones': {}, 'candidate_atr': .25}, asof)
    report = scan(selected, snapshot['minute'], asof) if not snapshot['minute'].empty else {}
    return decision(selected, observation, report, asof)


def _daily_source(data):
    if data.get('_history_selection') == FUTU:
        return CONTRACT + ' · 事后前复权'
    if data.get('history_origin'):
        return '富途原生日K归档'
    meta = data.get('coverage') or data.get('health', {})
    return '/'.join(str(meta[k]) for k in ('source', 'feed') if meta.get(k)) or 'UNKNOWN'


def _pick_history(pick, code, key):
    pick(code, key)
    st.session_state['experiment_mode'] = '历史回放'


@st.fragment
def render_home(selected, data, plan, decision, rows, decisions, replay_asof, wall_asof, pick, enabled=None):
    d = data[selected]
    st.markdown(CSS, unsafe_allow_html=True)
    toolbar = st.container(key='history-toolbar')
    display = st.container()
    config, asof, cycle, source_choice, comparison, mode = controls(selected, d, wall_asof, toolbar=toolbar)
    if asof is None:
        asof = wall_asof.replace(hour=0, minute=0)  # Empty analysis; never silently use another date.
        invalid_date = True
    else:
        invalid_date = False
    data = {code: select_history(value, source_choice) for code,value in data.items()}
    d = data[selected]
    historical = mode == '历史回放'
    period = '1H' if cycle == '1小时' else '1D'
    frame, source = (d['minute'], '富途分钟归档 → 纽约RTH 1H') if period == '1H' else (d['daily'], _daily_source(d))
    native_hourly = period == '1H' and (source_choice == FUTU or 'hourly_coverage' in d)
    if native_hourly:
        frame, source = d.get('futu_hourly', pd.DataFrame()), HOURLY
    candidate_data = d
    if period == '1D' and d.get('independent_coverage') and source_choice == '独立更新档案':
        meta = d['independent_coverage']
        frame, source = d['independent_daily'], f"{meta['source']}/{meta['feed']} · {meta['adjustment']}"
        candidate_data = dict(d, history_origin=None)
    if invalid_date:
        frame = frame.iloc[:0]
    baseline, _ = _analysis(frame, period, asof, source)
    state, chart = _analysis(frame, period, asof, source, config)
    before = _distance(candidate_data, baseline, BASELINE, period)
    after = _distance(candidate_data, state, config, period)
    comparison_view(comparison, baseline, state, before, after, config)
    latest_state, _ = _analysis(d['daily'] if not invalid_date else d['daily'].iloc[:0], '1D', asof, _daily_source(d))
    latest_date = latest_state['at'].date().isoformat() if latest_state['at'] is not None else None
    expected = latest_completed(asof if historical else wall_asof)
    freshness = '无可用日K' if latest_date is None else '行情已过期' if latest_date < expected else '日K截至最近完成交易日'
    if historical and not invalid_date:
        decision = _replay_decision(selected, d, asof)
        rows = [decision['focus']] if decision.get('focus') else []
    elif invalid_date:
        rows, decision = [], None
    setup = historical_plan(decision) if period == '1H' and not native_hourly else None
    basis_blocked = bool(d.get('_price_basis_unverified') or native_hourly)
    manual = None if basis_blocked else manual_prices(plan)
    if historical and plan and pd.Timestamp(plan['updated_at']) > asof:
        manual = None
    missing = state['at'] is None
    stale = latest_date is not None and latest_date < expected
    at_text = state['at'].strftime('%Y-%m-%d %H:%M 纽约') if state['at'] is not None else '暂无有效行情'
    if state['at'] is not None:
        at_text = pd.Timestamp(state['at']).tz_convert('America/New_York').strftime('%Y-%m-%d %H:%M 纽约')
    reference_asof = asof if historical else wall_asof
    price_refs = references(d['daily'] if not invalid_date else d['daily'].iloc[:0], reference_asof, _daily_source(d),
                            d.get('futu_coverage') if source_choice == FUTU else d.get('coverage'),
                            d.get('futu_hourly'), d.get('hourly_coverage'))
    readiness = target_readiness(plan, asof, basis_verified=not basis_blocked)
    # Fill the earlier container so the main layout stays above the expanded lab.
    with display:
        st.caption(f'{mode} · {source} · {cycle} · 数据截至 {at_text} · {freshness}')
        if basis_blocked:
            st.caption(PRICE_NOTE + ' 历史1H只描述趋势；1分钟ICT证据及实时交易资格关闭。')
            if plan:
                st.caption(PLAN_NOTE)
        if state['trend'] == 'UNKNOWN':
            st.info('资料不足：' + state['reason'])
        if native_hourly and (frame.empty or state['trend'] == 'UNKNOWN'):
            st.warning(MISSING + ' · ' + d.get('hourly_coverage', {}).get('reason', state['reason']))
            def switch_daily():
                st.session_state['experiment_period'] = '日K'
            st.button('切换至日K', key='hourly_fallback_daily', on_click=switch_daily)
        summary(selected[3:], state, stale, missing, at_text, historical)
        left, right = st.columns([1.7, 1], gap='medium')
        with left:
            with st.container(key='answer-chart'):
                st.subheader(f'{selected[3:]} · 主图', anchor='current-market-chart')
                st.caption(('日K' if period == '1D' else '1小时') + ' · 历史收盘资料')
                layer_mode = st.selectbox('指标图层', LAYER_MODES, index=1, key='ema_layer_mode')
                manual_layer = bool(manual and not historical and st.checkbox('叠加用户计划价格（待人工复核）'))
                if layer_mode != LAYER_MODES[0] and state['trend'] == 'UNKNOWN':
                    st.info(UNAVAILABLE)
                if chart.empty:
                    st.info('该时点无可用K线')
                else:
                    dates = chart.ts.map(str)
                    candle = dict(x=dates, open=chart.open, high=chart.high, low=chart.low, close=chart.close, name=period)
                    if native_hourly:
                        candle.update(text=[f"纽约 {a.tz_convert('America/New_York'):%Y-%m-%d %H:%M}–{b.tz_convert('America/New_York'):%H:%M} · 已完成 · {n:g}分钟<br>开 {o:g} 高 {h:g} 低 {l:g} 收 {c:g}<br>{HOURLY}"
                            for a,b,n,o,h,l,c in zip(chart.ts,chart.end_at,chart.duration_minutes,chart.open,chart.high,chart.low,chart.close)], hoverinfo='text')
                        st.caption('横轴UTC开始时间；悬浮查看纽约开始／结束与完整性。末根为收盘前30分钟。')
                    fig = go.Figure(go.Candlestick(**candle))
                    x = [dates.iloc[0], dates.iloc[-1]]
                    if layer_mode != LAYER_MODES[0] and state['trend'] != 'UNKNOWN':
                        if layer_mode == LAYER_MODES[2]:
                            add_ema_lines(fig, _ema_points(chart, period, asof, source, BASELINE), BASELINE, original=True)
                        add_ema_lines(fig, _ema_points(chart, period, asof, source, config), config)
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
                action(selected[3:], manual, plan, setup if historical else None, stale, basis_blocked=basis_blocked,
                       price_refs=price_refs, readiness=readiness)
                with st.expander('历史参考价计算证据'):
                    for level in price_refs['levels']:
                        st.write(level)
                    for reason in price_refs['missing']:
                        st.caption(reason)
        st.subheader('重点观察的15只证券（自选显示顺序）')
        st.caption('历史资料观察 · 显示顺序不是盈利概率排名；调整仅保留在当前浏览器会话。')
        allowed = focus_symbols(enabled if enabled is not None else list(data))
        all_enabled = [code for code in (enabled if enabled is not None else data) if code != 'US.VIX']
        preference = st.session_state.get('focus_symbols', allowed)
        preference = focus_symbols(all_enabled, preference)
        st.session_state['focus_symbols'] = preference
        with st.expander('调整重点观察证券及顺序'):
            st.multiselect('按加入顺序显示，最多15只；移除后重新加入可调整顺序', all_enabled,
                           max_selections=15, key='focus_symbols')
            def reset_focus():
                st.session_state['focus_symbols'] = focus_symbols(all_enabled)
            st.button('恢复已启用名单前15只', on_click=reset_focus)
        watch = [dict(symbol=code) for code in focus_symbols(all_enabled, st.session_state['focus_symbols'])]
        if not watch:
            st.info('暂无观察候选')
        with st.container(key='focus-grid'):
          for item in watch:
            code = item['symbol']
            with st.container(key='focus-card-'+code.replace('.', '-')):
                watch_frame = data[code]['daily'] if not invalid_date else data[code]['daily'].iloc[:0]
                watch_state, _ = _analysis(watch_frame, '1D', asof, _daily_source(data[code]))
                watch_at = watch_state['at']
                watch_date = pd.Timestamp(watch_at).tz_convert('America/New_York').strftime('%Y-%m-%d %H:%M 纽约') if watch_at is not None else '暂无资料'
                trend = watch_state['trend'] if watch_state['trend'] != 'UNKNOWN' else None
                hourly_frame = data[code].get('futu_hourly', pd.DataFrame())
                hourly_state, _ = _analysis(hourly_frame.iloc[:0] if invalid_date else hourly_frame, '1H', asof, HOURLY)
                refs = references(watch_frame, reference_asof, _daily_source(data[code]), data[code].get('futu_coverage'))
                candidate(code[3:], '历史资料 · 实时资格关闭', nearest_reference(refs), '查看历史图表',
                          data_at=watch_date, historical_trend=trend, volatility=watch_state['volatility'],
                          hourly_trend=hourly_state['trend'], close=watch_state['close'], source=_daily_source(data[code]),
                          data_status=('日K合格' if trend else '日K资料不足')+' / '+
                              ('1H合格' if hourly_state['trend'] != 'UNKNOWN' else '1H未验收或不足'))
                if st.button('查看图表 · '+code[3:], key='watch_'+code, on_click=pick, args=(code, None), width='stretch'):
                    st.rerun()
                with st.expander('详情'):
                    st.caption(data[code].get('hourly_coverage', {}).get('reason', '1H仅限历史图表；无1分钟ICT资格'))
    with st.expander('专业分析和计算依据'):
        st.caption(f'分析时点 {asof.isoformat()} · 周期 {period} · {source}')
        st.caption(f'最新原归档日K收盘 {latest_state["at"] or "暂无"} · 最近完成纽约交易日 {expected} · {freshness}')
        if d.get('independent_coverage'):
            st.write('独立更新档案', d['independent_coverage'])
        if basis_blocked and d.get('futu_coverage'):
            st.write('独立Futu日K来源与校验', d['futu_coverage'])
        if d.get('hourly_coverage'):
            st.write('独立原生60分钟来源与校验', d['hourly_coverage'])
        st.caption(RULES)
        st.caption('EMA图线每个点均复用该时点最近50根已完成K线及首根初始化；最早49根不画指标。'
                   '观察卡历史趋势使用原始参数，不参与评分或排名。')
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
        st.caption('实时行情尚未通过验收；实时ICT资格继续关闭。')
        st.caption('每日自动更新仍阻断 · 本地无人值守数据访问尚未验证' if st.session_state.get('_daily_update_status') == 'BLOCKED' else '每日更新状态见设置与审计')
        if d.get('daily_only'):
            st.caption('只有日K，1小时ICT资格不足')
