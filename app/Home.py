import streamlit as st


def _home_page() -> None:
    st.set_page_config(page_title="形态发现器", page_icon="📊", layout="wide")
    st.title("形态发现器")
    st.caption("里程碑 3B——本地样例与 Futu 前复权试点数据")
    st.info(
        "请从侧边栏查看今日扫描或逐图复核。只有明确点击刷新按钮时，系统才会连接 Futu OpenD。"
    )


navigation = st.navigation(
    (
        st.Page(_home_page, title="首页", icon=":material/home:", default=True),
        st.Page("pages/1_Today_Scan.py", title="今日扫描", icon=":material/table_view:"),
        st.Page("pages/2_Chart_Review.py", title="图表复核", icon=":material/candlestick_chart:"),
    )
)
navigation.run()
