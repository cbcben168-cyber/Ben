from pathlib import Path
import re
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from desk.i18n import zh, table, TEXT
from desk.clock import now_et, session, bounds
from desk.store import Store
from desk.provider import Provider
from desk.analytics import key_levels, aggregate_rth, observe, STAGES

ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title='ICT 交易工作台', page_icon='◈', layout='wide', initial_sidebar_state='collapsed')
from desk.diagnostics import initialize, panel, SafeStore
initialize(ROOT)

@st.cache_resource
def database():
    return SafeStore(Store(ROOT / 'data' / 'desk.sqlite3'))

try:
    store = database()
except Exception:
    import logging
    logging.getLogger('ict.stability').exception('数据库初始化失败')
    st.error('本地数据库暂时不可用。原始数据未被删除，请查看 data/stability.log；暂不允许写入备注或计划。')
    st.stop()
settings = store.settings()
st.markdown('''<style>.block-container{padding-top:2rem} h1{letter-spacing:-1px}
[data-testid="stMetric"]{background:#142036;padding:18px;border-radius:12px}
.stCaption{color:#a3b4cb}</style>''', unsafe_allow_html=True)
st.sidebar.title(TEXT['文案1'])
st.sidebar.caption(TEXT['文案2'])
page = st.sidebar.radio(TEXT['文案3'], ['交易工作台', '事件与备注', '设置与审计', 'SOP 与进度', '其他策略', '交易记录', '期权'])
symbol = st.sidebar.selectbox(TEXT['文案4'], settings['watchlist']) if settings['watchlist'] else None
st.sidebar.caption('Futu OpenD · 127.0.0.1:11111\n无账户查询 · 无订单接口')


@st.cache_resource
def provider():
    return Provider()


@st.cache_resource
def loader():
    from desk.market_loader import MarketLoader
    source=provider()
    return MarketLoader(source.fetch)


def market_data(code, tick):
    return loader().get(code,tick)


def clear_market_data():
    loader().clear()


market_data.clear=clear_market_data
market_data.loading=lambda: bool(loader().diagnostics()['pending'])
market_data.diagnostics=lambda: loader().diagnostics()


def events_table():
    channel=st.radio('事件类别',['市场观察与人工记录','系统健康诊断'],horizontal=True)
    st.dataframe(table(store.table('market_events' if channel=='市场观察与人工记录' else 'system_events')), width='stretch', hide_index=True)


if page == '交易工作台':
    from desk.workspace import render
    render(store, settings, market_data)
elif page == '设置与审计':
    st.title(TEXT['文案5'])
    with st.form('parameters'):
        codes = st.text_input(TEXT['文案8'], ', '.join(settings['watchlist']))
        distance = st.number_input(TEXT['文案9'], min_value=0.1, max_value=1000.0, value=float(settings['distance_bps']))
        candidate_atr = st.number_input('候选最大关键价距离（ATR倍数）', min_value=0.01, max_value=5.0, value=float(settings['candidate_atr']), step=0.05)
        refresh = st.number_input(TEXT['文案10'], min_value=30, max_value=3600, value=int(settings['refresh_seconds']))
        layers = st.checkbox(TEXT['文案11'], value=settings['layers'])
        if st.form_submit_button(TEXT['文案12']):
            items = list(dict.fromkeys(c.strip().upper() for c in codes.split(',') if c.strip()))
            items = [c if c.startswith('US.') else 'US.'+c for c in items]
            if not items or len(items) > 20 or any(not re.fullmatch(r'US\.[A-Z][A-Z0-9.-]{0,14}', c) for c in items):
                st.error(TEXT['文案26'])
            else:
                for k,v in dict(watchlist=items, distance_bps=distance, candidate_atr=candidate_atr, refresh_seconds=refresh, layers=layers).items():
                    store.save(k,v)
                st.rerun()
    st.subheader(TEXT['文案6'])
    if symbol:
        z = settings['zones'].get(symbol, {})
        with st.form('zone'):
            low = st.number_input(TEXT['文案14'], min_value=0.0, value=float(z.get('low', 0)))
            high = st.number_input(TEXT['文案15'], min_value=0.0, value=float(z.get('high', 0)))
            direction = st.selectbox(TEXT['文案16'], ['LONG', 'SHORT'], index=1 if z.get('direction') == 'SHORT' else 0, format_func=zh)
            invalid = st.number_input(TEXT['文案17'], min_value=0.0, value=float(z.get('invalid', 0)))
            stage = st.selectbox(TEXT['文案18'], STAGES[1:4], index=STAGES[1:4].index(z.get('stage', '等待 Sweep')), format_func=zh)
            save = st.form_submit_button(TEXT['文案19'])
            delete = st.form_submit_button(TEXT['文案20'])
            if save or delete:
                zones = dict(settings['zones'])
                if delete:
                    zones.pop(symbol, None)
                elif low <= 0 or high < low or (invalid and ((direction == 'LONG' and invalid >= low) or (direction == 'SHORT' and invalid <= high))):
                    st.error(TEXT['文案29'])
                    st.stop()
                else:
                    zones[symbol] = dict(low=low, high=high, direction=direction, invalid=invalid, stage=stage)
                store.save('zones', zones)
                st.rerun()
    st.subheader(TEXT['文案7'])
    st.dataframe(table(store.table('audit')), width='stretch', hide_index=True)
elif page == '事件与备注':
    st.title(TEXT['文案13'])
    with st.form('note', clear_on_submit=True):
        note = st.text_area(TEXT['文案21'], max_chars=4000)
        if st.form_submit_button(TEXT['文案27']) and note.strip():
            store.event('NOTE', symbol or '', note.strip())
            st.success(TEXT['文案28'])
    events_table()
elif page == 'SOP 与进度':
    st.title(TEXT['文案22'])
    st.markdown(zh('1. 核对权限、时间戳和 Session。\n2. 复核前日 RTH、PRE、NIGHT 和 OR 的完整性。\n3. 设置人工区域与失效价。\n4. 人工核对已完成 K 线，记录 Sweep/MSS/FVG 阶段。\n5. 记录触价原因与备注。'))
    st.info(TEXT['文案23'])
    st.markdown((ROOT/'PROGRESS.md').read_text(encoding='utf-8'))
else:
    st.title(page)
    st.warning(TEXT['文案24'])
    st.write(TEXT['文案25'])
