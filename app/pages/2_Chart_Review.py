import os
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from tv_quant.data_quality import load_standardized_csv
from tv_quant.pattern_finder.cache import (
    DEFAULT_CACHE_ROOT,
    cached_symbols,
    load_cache_entry,
)
from tv_quant.pattern_finder.charts import build_candlestick_figure
from tv_quant.pattern_finder.flat_base import FlatBaseResult, detect_flat_base
from tv_quant.pattern_finder.fixtures import load_fixture, load_fixtures
from tv_quant.pattern_finder.models import chart_series_from_frame, ohlcv_frame_from_series
from tv_quant.pattern_finder.validation import (
    DEFAULT_VALIDATION_PATH,
    HUMAN_LABELS,
    MAX_NOTE_LENGTH,
    REASON_TAGS,
    ValidationStoreError,
    append_validation,
    build_validation,
    latest_validations,
    read_validation_history,
)


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


@st.cache_data(ttl="30s", max_entries=8, show_spinner=False)
def _cached_validation_history(path: str, modified_ns: int):
    del modified_ns
    return read_validation_history(path)


def _render_flat_base_diagnostics(result: FlatBaseResult | None) -> None:
    if result is None:
        st.info(
            "Flat Base diagnostics unavailable: data quality and 120-bar history "
            "are required."
        )
        return
    selected = result.selected
    st.caption(
        f"Flat Base: {'YES' if result.pattern_flat_base else 'NO'} | "
        f"Detector Version: {result.detector_version}"
    )
    st.caption(
        f"Base Window: {selected.base_start.date().isoformat()} to "
        f"{selected.base_end.date().isoformat()} | Base Length: {selected.base_length} | "
        f"Base Depth: {selected.base_depth_pct:.6f} | "
        f"Bottom Tests: {selected.bottom_test_count} | "
        f"Bottom Tolerance: {selected.bottom_tolerance_pct:.6f} | "
        f"Normalized Slope: {selected.normalized_slope:.8f}"
    )
    st.caption(
        f"Support: {selected.support_level:.4f} | "
        f"Resistance: {selected.resistance_level:.4f} | "
        f"Resistance Raw: {selected.resistance_raw:.4f} | "
        f"Resistance Upper Quantile: {selected.resistance_upper_quantile:.4f} | "
        f"Resistance Spike Adjusted: "
        f"{'YES' if selected.resistance_spike_adjusted else 'NO'} | "
        f"ATR14 T0: {selected.atr14_t0:.6f}"
    )


if source == "Fixture":
    st.caption("Daily fixture candlestick with volume and base reference levels")
    symbols = tuple(fixture.symbol for fixture in load_fixtures())
    selected_symbol = st.selectbox("Fixture symbol", symbols)
    fixture = load_fixture(selected_symbol)
    flat_base = detect_flat_base(ohlcv_frame_from_series(fixture))

    _render_flat_base_diagnostics(flat_base)
    st.plotly_chart(
        build_candlestick_figure(fixture, flat_base=flat_base),
        width="stretch",
        config={"displayModeBar": True, "scrollZoom": True},
    )
else:
    st.caption("Futu QFQ daily candlestick and volume from the local per-symbol cache")
    cache_root = Path(os.getenv("PATTERN_FINDER_CACHE_ROOT", str(DEFAULT_CACHE_ROOT)))
    validation_path = Path(
        os.getenv("PATTERN_FINDER_VALIDATION_PATH", str(DEFAULT_VALIDATION_PATH))
    )
    symbols = cached_symbols(cache_root)
    if not symbols:
        st.info("No local M3B cache is available. Run the staged expansion CLI first.")
        st.stop()
    selected_symbol = st.selectbox("Cached symbol", symbols)
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
            flat_base = (
                detect_flat_base(frame)
                if report.passed and len(frame) >= 120
                else None
            )
            _render_flat_base_diagnostics(flat_base)
            st.plotly_chart(
                build_candlestick_figure(series, flat_base=flat_base),
                width="stretch",
                config={"displayModeBar": True, "scrollZoom": True},
            )
            if flat_base is not None:
                try:
                    history = _cached_validation_history(
                        validation_path.as_posix(),
                        validation_path.stat().st_mtime_ns
                        if validation_path.exists()
                        else 0,
                    )
                except ValidationStoreError as error:
                    history = ()
                    validation_store_ok = False
                    st.error(f"Validation history is invalid: {error}")
                else:
                    validation_store_ok = True

                scan_date = flat_base.selected.base_end.date().isoformat()
                key = (selected_symbol, flat_base.detector_version, scan_date)
                current = latest_validations(history).get(key)
                history_count = sum(record.key == key for record in history)
                if current is None:
                    st.caption("Human validation: 未人工验证 | History: 0")
                else:
                    st.caption(
                        f"Human validation: {current.human_label} | "
                        f"History: {history_count} | "
                        f"Reason Tags: {', '.join(current.reason_tags) or '-'} | "
                        f"Note: {current.note or '-'}"
                    )

                with st.form(
                    f"flat_base_review_{selected_symbol}",
                    clear_on_submit=True,
                ):
                    human_label = st.segmented_control(
                        "Human label",
                        HUMAN_LABELS,
                        default=None,
                        required=True,
                        key=f"human_label_{selected_symbol}",
                    )
                    reason_tags = st.pills(
                        "Reason tags",
                        REASON_TAGS,
                        selection_mode="multi",
                        disabled=human_label not in HUMAN_LABELS[1:],
                        key=f"reason_tags_{selected_symbol}",
                    )
                    note = st.text_area(
                        "Note",
                        max_chars=MAX_NOTE_LENGTH,
                        key=f"human_note_{selected_symbol}",
                    )
                    submitted = st.form_submit_button(
                        "Save validation",
                        icon=":material/save:",
                        disabled=not validation_store_ok,
                    )

                if submitted and human_label is not None:
                    selected = flat_base.selected
                    scan_row = {
                        "Symbol": selected_symbol,
                        "Detector Version": flat_base.detector_version,
                        "Flat Base": "YES" if flat_base.pattern_flat_base else "NO",
                        "Base Length": selected.base_length,
                        "Base Depth": selected.base_depth_pct,
                        "Bottom Tests": selected.bottom_test_count,
                        "Normalized Slope": selected.normalized_slope,
                    }
                    try:
                        record = build_validation(
                            scan_row,
                            selected.base_end.date(),
                            human_label,
                            () if human_label == "像" else tuple(reason_tags or ()),
                            note or "",
                            datetime.now(UTC),
                        )
                    except ValueError as error:
                        st.error(f"Validation rejected: {error}")
                    else:
                        append_validation(validation_path, record)
                        st.cache_data.clear()
                        st.success("Validation saved")
