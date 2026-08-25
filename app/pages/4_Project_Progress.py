"""Versioned project progress page."""

import streamlit as st

from tv_quant.pattern_finder.application.system_dashboard import load_project_progress


st.title("Project Progress")
progress = load_project_progress(st.session_state["runtime_config"].repository_root / "config/project_progress.yaml")
st.progress(progress.percent_complete / 100, text=f"Overall {progress.percent_complete}%")
st.dataframe(
    [
        {"Milestone": item.milestone_id, "Name": item.name, "Status": item.status, "Progress": f"{item.percent_complete}%"}
        for item in progress.milestones
    ],
    hide_index=True,
    width="stretch",
)
