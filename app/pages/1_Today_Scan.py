import pandas as pd
import streamlit as st

from tv_quant.pattern_finder.fixtures import load_fixtures


st.set_page_config(page_title="Today Scan", page_icon="📋", layout="wide")
st.title("Today Scan")
st.caption("Local fixture data only — no live market scan")

rows = [
    {
        "Symbol": fixture.symbol,
        "Pattern": fixture.pattern_label,
        "Bars": len(fixture.bars),
        "Base Start": fixture.base_start.date().isoformat(),
        "Base End": fixture.base_end.date().isoformat(),
        "Support": fixture.support,
        "Resistance": fixture.resistance,
    }
    for fixture in load_fixtures()
]
st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

