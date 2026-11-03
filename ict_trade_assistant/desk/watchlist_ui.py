"""Watchlist management never requests market data."""
import pandas as pd
import streamlit as st
from .watchlist import PRESET


def render_watchlist(store):
    st.subheader('观察名单管理 · v0.4.1')
    st.caption('支持美股及ETF；停用不参与加载和排名。删除只移出名单，保留计划、备注和历史证据。VIX仅作背景。')
    notice = st.session_state.pop('watchlist_notice', None)
    if notice:
        st.success(notice)
    with st.form('watchlist_add', clear_on_submit=True):
        code = st.text_input('添加证券代码', placeholder='SMH 或 US.AAPL')
        group = st.text_input('新证券分组', value='自选')
        if st.form_submit_button('添加证券'):
            try:
                added = store.manage_watchlist('add', code, group=group)
                st.session_state.watchlist_notice = '证券已添加' if added else '代码已存在，已自动去重；原分组及启停状态保留。'
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
    st.caption('ETF AUM Top20预设：'+PRESET['source']+'；登记日期 '+PRESET['recorded_at']+'；'+PRESET['ranking_basis']+'。原始统计日期未提供，未经实时排名核验。')
    if st.button('导入美国ETF AUM Top20预设'):
        added = store.manage_watchlist('import_top20')
        st.session_state.watchlist_notice = f'Top20导入完成：新增{added}只；已有代码去重，用户分组及启停状态保留。'
        st.rerun()
    entries = store.settings()['watchlist_entries']
    st.write(f'名单共 {len(entries)} 只 · 已启用 {sum(e["enabled"] for e in entries)} 只 · 总量不限于20')
    query = st.text_input('搜索代码或分组').strip().upper()
    selected_group = st.selectbox('按分组筛选', ['全部分组']+sorted({e['group'] for e in entries}))
    visible = [e for e in entries if (not query or query in e['symbol'].upper() or query in e['group'].upper())
               and (selected_group == '全部分组' or e['group'] == selected_group)]
    st.dataframe(pd.DataFrame([{'代码': e['symbol'], '状态': '启用' if e['enabled'] else '停用', '分组': e['group']} for e in visible],
                             columns=['代码', '状态', '分组']), hide_index=True, width='stretch')
    if not visible:
        st.info('没有匹配的证券。')
        return
    symbol = st.selectbox('管理证券', [e['symbol'] for e in visible])
    entry = next(e for e in visible if e['symbol'] == symbol)
    with st.form('watchlist_manage_'+symbol):
        enabled = st.checkbox('启用此证券', value=entry['enabled'])
        group = st.text_input('证券分组', value=entry['group'])
        update = st.form_submit_button('保存启用状态与分组')
        delete = st.form_submit_button('从观察名单删除')
        if update or delete:
            try:
                store.manage_watchlist('delete' if delete else 'update', symbol, group=group, enabled=enabled)
                st.session_state.watchlist_notice = f'{symbol} 已从名单删除，原计划保留。' if delete else f'{symbol} 状态和分组已保存。'
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
