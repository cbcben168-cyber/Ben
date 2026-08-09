import os
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from tv_quant.pattern_finder.cache import DEFAULT_CACHE_ROOT, flat_base_scan_rows
from tv_quant.pattern_finder.flat_base import detect_flat_base
from tv_quant.pattern_finder.fixtures import load_fixtures
from tv_quant.pattern_finder.futu_service import refresh_pilot_universe
from tv_quant.pattern_finder.models import ohlcv_frame_from_series


st.set_page_config(page_title="Today Scan", page_icon="📋", layout="wide")
st.title("Today Scan")
source = st.segmented_control(
    "Data source",
    ("Fixture", "Cache / Futu"),
    default="Fixture",
    required=True,
    key="today_scan_source",
)


@st.cache_data(ttl="30s", max_entries=4, show_spinner=False)
def _cached_scan(cache_root: str, as_of_iso: str) -> tuple[dict[str, object], ...]:
    return flat_base_scan_rows(cache_root, datetime.fromisoformat(as_of_iso))


if source == "Fixture":
    st.caption("Deterministic local fixture data")
    rows = []
    for fixture in load_fixtures():
        result = detect_flat_base(ohlcv_frame_from_series(fixture))
        selected = result.selected
        rows.append(
            {
                "Symbol": fixture.symbol,
                "Pattern": fixture.pattern_label,
                "Bars": len(fixture.bars),
                "Flat Base": "YES" if result.pattern_flat_base else "NO",
                "Base Length": selected.base_length,
                "Base Depth": selected.base_depth_pct,
                "Bottom Tests": selected.bottom_test_count,
                "Slope": selected.normalized_slope,
                "Support": selected.support_level,
                "Resistance": selected.resistance_level,
            }
        )
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
else:
    cache_root = Path(os.getenv("PATTERN_FINDER_CACHE_ROOT", str(DEFAULT_CACHE_ROOT)))
    as_of = datetime.now(UTC).replace(second=0, microsecond=0)
    st.caption(f"Pilot cache: {cache_root} | Daily bars | QFQ | XNYS")
    if st.button(
        "Refresh pilot from Futu OpenD",
        icon=":material/refresh:",
        type="primary",
    ):
        try:
            with st.spinner("Updating eight pilot symbols from Futu OpenD..."):
                entries = refresh_pilot_universe(
                    cache_root=cache_root,
                    as_of_utc=datetime.now(UTC),
                )
        except Exception as error:
            st.error(f"Futu refresh failed: {error}")
        else:
            st.cache_data.clear()
            st.success(f"Updated {len(entries)} pilot symbols.")

    rows = _cached_scan(cache_root.as_posix(), as_of.isoformat())
    columns = (
        "Symbol",
        "Cache",
        "Flat Base",
        "Base Length",
        "Base Depth",
        "Bottom Tests",
        "Slope",
        "Rows",
        "Data Quality",
        "Issues",
        "Adjustment",
    )
    st.dataframe(pd.DataFrame(rows).loc[:, columns], hide_index=True, width="stretch")
