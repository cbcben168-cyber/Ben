import streamlit as st

from tv_quant.pattern_finder.charts import build_candlestick_figure
from tv_quant.pattern_finder.fixtures import load_fixture, load_fixtures


st.set_page_config(page_title="Chart Review", page_icon="🕯️", layout="wide")
st.title("Chart Review")
st.caption("Daily fixture candlestick with volume and base reference levels")

symbols = tuple(fixture.symbol for fixture in load_fixtures())
selected_symbol = st.selectbox("Fixture symbol", symbols)
fixture = load_fixture(selected_symbol)

st.caption(
    f"Base Window: {fixture.base_start.date().isoformat()} to "
    f"{fixture.base_end.date().isoformat()} | Support: {fixture.support:.2f} | "
    f"Resistance: {fixture.resistance:.2f}"
)
st.plotly_chart(
    build_candlestick_figure(fixture),
    width="stretch",
    config={"displayModeBar": True, "scrollZoom": True},
)
