import streamlit as st

from tv_quant.pattern_finder.application.system_dashboard import (
    build_dashboard_state,
    latest_snapshot_binding,
    profile_registry_binding,
)
from tv_quant.pattern_finder.runtime.config import RuntimeConfig


def _home_page() -> None:
    st.title("形态发现器")
    st.caption("Pattern Research System｜本地运行、持久化与研究状态总览")
    state = build_dashboard_state(st.session_state["runtime_config"])
    columns = st.columns(4)
    columns[0].metric("System", state.system_status)
    columns[1].metric("Database", state.database_status)
    columns[2].metric("DB Schema", f"v{state.schema_version}")
    columns[3].metric("Futu", state.futu_status)
    st.subheader("Research status")
    st.caption(
        f"Database {state.database_status}｜Active Profile {state.active_profile}｜"
        f"Data Freshness {state.data_freshness}"
    )
    st.dataframe(
        [
            {"Status": "Active Profile", "Value": state.active_profile},
            {"Status": "Latest Snapshot", "Value": state.snapshot_time or "-"},
            {"Status": "Universe", "Value": f"MEMBER {state.member_count} / FAIL {state.fail_count} / QUARANTINE {state.quarantine_count}"},
            {"Status": "Last Scan", "Value": state.last_scan},
            {"Status": "Candidates", "Value": str(state.candidate_count)},
            {"Status": "Pending Review", "Value": str(state.pending_review_count)},
            {"Status": "Last Backtest", "Value": state.last_backtest},
            {"Status": "Data Freshness", "Value": state.data_freshness},
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption("Only an explicit refresh action connects to Futu OpenD.")


st.set_page_config(page_title="Pattern Research System", page_icon="📊", layout="wide")

if "runtime_config" not in st.session_state:
    st.session_state["runtime_config"] = RuntimeConfig.from_environment()
if "universe_snapshot_store" not in st.session_state:
    store, snapshot_id = latest_snapshot_binding(
        st.session_state["runtime_config"]
    )
    st.session_state["universe_snapshot_store"] = store
    if snapshot_id is not None:
        st.session_state["universe_snapshot_id"] = snapshot_id
if "universe_profile_registry" not in st.session_state:
    st.session_state["universe_profile_registry"] = profile_registry_binding(
        st.session_state["runtime_config"]
    )


navigation = st.navigation(
    (
        st.Page(_home_page, title="首页", icon=":material/home:", default=True),
        st.Page("pages/1_Today_Scan.py", title="今日扫描", icon=":material/table_view:"),
        st.Page("pages/2_Chart_Review.py", title="图表复核", icon=":material/candlestick_chart:"),
        st.Page("pages/3_Universe_Settings.py", title="股票池设置", icon=":material/tune:"),
        st.Page("pages/4_Project_Progress.py", title="Project Progress", icon=":material/checklist:"),
        st.Page("pages/5_Diagnostics.py", title="Diagnostics", icon=":material/monitor_heart:"),
    )
)
navigation.run()
