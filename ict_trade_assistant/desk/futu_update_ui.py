"""Read-only status panel; only an explicit click starts the local updater."""
from datetime import datetime, timezone
import json
from pathlib import Path

import streamlit as st

from .daily_update import latest_completed
from .futu_update import FutuVersions, start_update, task_status


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


@st.fragment(run_every=2)
def render_futu_update(baseline, clear, root=None):
    versions = FutuVersions(baseline, root)
    token = versions.pointer.stat().st_mtime_ns if versions.pointer.exists() else None
    seen = st.session_state.get('_futu_version_seen', token)
    st.session_state['_futu_version_seen'] = token
    if seen != token:
        clear()
        from .workspace import chart_data, historical_ict
        chart_data.clear()
        historical_ict.clear()
        st.rerun()
    st.subheader('历史行情更新')
    try:
        current = versions.summary()
    except (OSError, ValueError) as exc:
        st.error('当前Futu历史档案无法核验：' + str(exc))
        return
    target = latest_completed(datetime.now(timezone.utc))
    running, status = task_status(versions)
    progress = read_json(versions.root / 'capture_progress.json')
    st.write('当前数据截至：' + current['last'])
    st.write(f"覆盖证券：{current['symbols']}/23")
    st.write('数据来源：Futu前复权日K')
    st.write('当前版本：' + current['version'])
    st.write('最新完整交易日：' + target)
    if running:
        verifying = '校验' in status.get('phase', '')
        detail = status if verifying else progress or status
        completed = min(23, int(detail.get('completed', 0)))
        st.info('更新中 · ' + detail.get('phase', '正在检查'))
        st.progress(completed / 23, text=f'已完成 {completed}/23 只证券')
    elif status.get('status') == 'FAILED':
        st.error('更新失败：' + status.get('reason', '请稍后重试。'))
    elif status.get('status') == 'SUCCESS':
        st.success(f"更新成功 · 新增交易日 {status['added_days']} · 验证通过 23/23")
    elif current['last'] >= target:
        st.info('历史行情已经是最新，无需更新。')
    else:
        st.info('可以更新')
    if st.button('检查并更新历史行情', disabled=running, key='futu_daily_update'):
        try:
            if start_update(versions, Path(__file__).resolve().parents[1] / 'scripts/update_futu_daily.py'):
                st.rerun()
            else:
                st.info('已有更新任务正在运行。')
        except (OSError, ValueError):
            st.error('无法启动本地历史更新，请检查工作目录权限。')
    if status.get('status_warning'):
        st.warning(status['status_warning'])
    if status.get('status') == 'UP_TO_DATE' and not running:
        st.caption('已重新核查完整QFQ历史及复权事件；没有新版本。')
    st.caption('仅更新日K趋势和因子；不授予实时ICT资格。人工计划价格尺度尚未核实。')
