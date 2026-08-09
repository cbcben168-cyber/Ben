import streamlit as st


st.set_page_config(page_title="Pattern Finder", page_icon="📈", layout="wide")
st.title("Pattern Finder")
st.caption("Milestone 2 - local Fixture and Futu QFQ pilot data")
st.info(
    "Use the sidebar to inspect pilot cache status or review daily candlesticks. "
    "Futu OpenD is contacted only after an explicit refresh action."
)
