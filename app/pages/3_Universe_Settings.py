"""Initialized published universe profile status page."""

import streamlit as st

from tv_quant.pattern_finder.universe_foundation import ProfileRegistry
from tv_quant.pattern_finder.universe_foundation.ui_read_model import (
    EvaluationUiState,
    render_profile_status,
    render_security_evaluation,
)


st.set_page_config(page_title="股票池设置", page_icon="📋", layout="wide")
st.title("股票池设置")

registry = st.session_state.get("universe_profile_registry")
if not isinstance(registry, ProfileRegistry):
    st.error("Universe profile registry must be initialized before rendering.")
    st.stop()

try:
    render_profile_status(registry=registry, profile_version_id="CORE:v1")
except RuntimeError as exc:
    st.error(str(exc))

evaluation_state = st.session_state.get("universe_evaluation_state")
if evaluation_state is not None:
    if not isinstance(evaluation_state, EvaluationUiState):
        st.error("Universe evaluation state must be produced by the read model.")
    else:
        render_security_evaluation(state=evaluation_state)
