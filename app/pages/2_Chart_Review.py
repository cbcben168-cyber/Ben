import os
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from tv_quant.data_quality import load_standardized_csv
from tv_quant.pattern_finder.cache import DEFAULT_CACHE_ROOT, load_cache_entry
from tv_quant.pattern_finder.charts import build_candlestick_figure
from tv_quant.pattern_finder.fixtures import load_fixture, load_fixtures
from tv_quant.pattern_finder.models import chart_series_from_frame
from tv_quant.pattern_finder.universe import PILOT_SYMBOLS


st.set_page_config(page_title="Chart Review", page_icon="🕯️", layout="wide")
st.title("Chart Review")
source = st.segmented_control(
    "Data source",
    ("Fixture", "Cache / Futu"),
    default="Fixture",
    required=True,
    key="chart_review_source",
)


@st.cache_data(ttl="30s", max_entries=16, show_spinner=False)
def _cached_frame(path: str, modified_ns: int):
    del modified_ns
    return load_standardized_csv(Path(path))[0]


if source == "Fixture":
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
else:
    st.caption("Futu QFQ daily candlestick and volume from the local per-symbol cache")
    cache_root = Path(os.getenv("PATTERN_FINDER_CACHE_ROOT", str(DEFAULT_CACHE_ROOT)))
    selected_symbol = st.selectbox("Pilot symbol", PILOT_SYMBOLS)
    try:
        entry = load_cache_entry(
            selected_symbol,
            cache_root=cache_root,
            as_of_utc=datetime.now(UTC),
        )
    except Exception as error:
        st.error(f"Cache read failed: {error}")
    else:
        if entry is None:
            st.info("No local cache for this symbol. Use Today Scan to run an explicit Futu refresh.")
        else:
            report = entry.quality
            if report.passed:
                st.success(
                    f"Data Quality: PASS | {entry.rows} rows | "
                    f"latest {report.last_session.isoformat()}"
                )
            else:
                issues = list(report.errors)
                if report.missing_sessions:
                    issues.append(f"{len(report.missing_sessions)} missing XNYS session(s)")
                st.warning("Data Quality: FAIL | " + "; ".join(issues))
            frame = _cached_frame(entry.path.as_posix(), entry.path.stat().st_mtime_ns)
            series = chart_series_from_frame(frame, selected_symbol, max_bars=150)
            st.plotly_chart(
                build_candlestick_figure(series),
                width="stretch",
                config={"displayModeBar": True, "scrollZoom": True},
            )
