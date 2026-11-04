"""Show actual update coverage and blocked access; never obtain connector credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import streamlit as st
import pandas as pd
from .daily_update import LocalAlpaca, make_plan, run_update, probe_local, latest_completed
from .history_import import DailyArchive


def read_json(path):
    try:return json.loads(path.read_text(encoding='utf8'))
    except (OSError,ValueError):return {}


def render_update(root, settings, legacy, base, clear):
    root=Path(root);now=datetime.now(timezone.utc)
    client=LocalAlpaca();local=client.preflight()
    access=read_json(root/'access.json');recent=read_json(root/'latest.json')
    verified=bool(local['configured'] and access.get('status')=='PASS' and
                  (pd.Timestamp(now)-pd.Timestamp(access['checked_at'])).total_seconds()<86400)
    st.subheader('每日历史更新 · v0.4.3')
    st.caption('历史资料、当前实时报价、ICT资格分别判断：本页只处理日K；实时行情未连接，ICT实时资格关闭。')
    if not verified:
        st.warning('BLOCKED：本地无人值守数据访问尚未验证。连接器可用不代表Windows任务可用。未注册每日自动更新任务。')
    st.write('最近完成的NYSE交易日：'+latest_completed(now))
    st.write('最近更新结果：'+str(recent.get('status','NOT_RUN'))+' · '+str(recent.get('completed_at','尚无执行记录')))
    st.caption('06:30香港时间可能仍处于纽约供应商日内。为避免保存未完成日K，程序保守等待纽约次日00:15；未到时记录PENDING_PROVIDER_DATA。供应商最终性仍未验证。')
    updates=DailyArchive(root/'updates.sqlite3')
    rows=make_plan(settings['watchlist_entries'],legacy,base,updates,now)
    old={r['symbol']:r for r in recent.get('rows',[])}
    st.dataframe(pd.DataFrame([dict(证券=r['symbol'],应截至=r['target'],当前截至=r['last'] or '无',
                独立更新截至=r['update_last'] or '无',缺失日期='、'.join(r['missing']) or '0',
                最近结果=old.get(r['symbol'],{}).get('status','NOT_RUN'),原因=old.get(r['symbol'],{}).get('reason','')) for r in rows]),hide_index=True,width='stretch')
    st.caption('独立更新档案不拼接原FUTU冻结快照或v0.4.2未确认复权的日线。每次请求逐证券，默认间隔6秒、至多3次尝试；同日冲突拒绝。')
    if st.button('验证本地SIP历史接口',disabled=not local['configured']):
        probe_local(root);st.rerun()
    if st.button('立即检查更新',disabled=not verified):
        run_update(root,settings['watchlist_entries'],legacy,base,client=client)
        clear();st.rerun()
    with st.expander('更新日志与失败状态'):
        st.json(dict(local_access=local,verified_access=access,last_run=recent))
