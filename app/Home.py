from pathlib import Path

import streamlit as st

from tv_quant.pattern_finder.universe_foundation import ProfileRegistry, core_v1


def _initialized_profile_registry() -> ProfileRegistry:
    registry = ProfileRegistry(
        Path(__file__).resolve().parents[1] / "data" / "pattern_finder" / "universe_profiles"
    )
    registry.bootstrap(core_v1())
    return registry


def _home_page() -> None:
    st.set_page_config(page_title="形态发现器", page_icon="📊", layout="wide")
    st.title("形态发现器")
    st.caption("里程碑 3B——本地样例与 Futu 前复权试点数据")
    st.info(
        "请从侧边栏查看今日扫描或逐图复核。只有明确点击刷新按钮时，系统才会连接 Futu OpenD。"
    )


if "universe_profile_registry" not in st.session_state:
    st.session_state["universe_profile_registry"] = _initialized_profile_registry()


navigation = st.navigation(
    (
        st.Page(_home_page, title="首页", icon=":material/home:", default=True),
        st.Page("pages/1_Today_Scan.py", title="今日扫描", icon=":material/table_view:"),
        st.Page("pages/2_Chart_Review.py", title="图表复核", icon=":material/candlestick_chart:"),
        st.Page("pages/3_Universe_Settings.py", title="股票池设置", icon=":material/tune:"),
    )
)
navigation.run()
