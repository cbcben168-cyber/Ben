"""Non-secret local system diagnostics."""

import streamlit as st

from tv_quant.pattern_finder.application.system_dashboard import build_diagnostics_state


st.title("Diagnostics")
state = build_diagnostics_state(st.session_state["runtime_config"])
st.dataframe(
    [
        {"Diagnostic": label, "Value": value}
        for label, value in (
            ("App version", state.app_version), ("Git commit", state.git_commit),
            ("Python", state.python_version), ("Database path", state.database_path),
            ("DB schema", state.schema_version), ("Runtime PID", state.runtime_pid),
            ("Port", state.port), ("Uptime", state.uptime), ("Futu", state.futu_connection),
            ("Data directory", state.data_directory), ("Log directory", state.log_directory),
            ("Latest error", state.latest_error or "-"),
            ("Latest migration", state.latest_migration or "-"),
            ("Latest Snapshot integrity", state.latest_snapshot_integrity),
        )
    ],
    hide_index=True,
    width="stretch",
)
