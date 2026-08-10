import os
from datetime import UTC, datetime
from pathlib import Path

import streamlit as st

from tv_quant.data_quality import load_standardized_csv
from tv_quant.pattern_finder.cache import DEFAULT_CACHE_ROOT, cached_symbols, load_cache_entry
from tv_quant.pattern_finder.charts import build_candlestick_figure
from tv_quant.pattern_finder.flat_base import FlatBaseResult, detect_flat_base
from tv_quant.pattern_finder.fixtures import load_fixture, load_fixtures
from tv_quant.pattern_finder.models import chart_series_from_frame, ohlcv_frame_from_series
from tv_quant.pattern_finder.pattern_registry import enabled_pattern_profiles
from tv_quant.pattern_finder.review import flat_base_review_input
from tv_quant.pattern_finder.validation import (
    DEFAULT_MIGRATION_LEDGER_PATH,
    DEFAULT_VALIDATION_PATH,
    HUMAN_LABELS,
    LEGACY_VALIDATION_PATH,
    MAX_NOTE_LENGTH,
    VALIDATION_RESULT_LABELS,
    ValidationStoreError,
    append_validation,
    build_pattern_validation,
    latest_validations,
    migrate_legacy_validations,
    read_validation_history,
)


st.set_page_config(page_title="图表复核", page_icon="🕯️", layout="wide")
st.title("图表复核")
profiles = enabled_pattern_profiles()
profile_names = tuple(profile.display_name_zh for profile in profiles)
selected_profile_name = st.selectbox("当前查看形态", profile_names)
profile = next(item for item in profiles if item.display_name_zh == selected_profile_name)
st.caption(f"当前评价形态：{profile.display_name_zh}")
source = st.segmented_control(
    "数据来源", ("本地样例", "缓存 / Futu"), default="本地样例", required=True,
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


def _format_diagnostic(value: int | float, format_spec: str | None) -> str:
    if format_spec == "integer":
        return str(int(value))
    if format_spec == "percent":
        return f"{float(value):.4%}"
    if format_spec:
        return format(value, format_spec)
    return str(value)


def _render_diagnostics(result: FlatBaseResult | None) -> None:
    if result is None:
        st.info("无法显示平底形态诊断：需要数据质量通过且至少有 120 根日K。")
        return
    review_input = flat_base_review_input(result)
    computer_result = review_input.computer_result
    st.caption(
        f"电脑判断：{'是' if computer_result == 'YES' else '否'}｜"
        f"检测器版本：{result.detector_version}"
    )
    values = review_input.diagnostics
    st.caption("｜".join(
        f"{field.display_name_zh}：{_format_diagnostic(values[field.key], field.format_spec)}"
        for field in profile.diagnostic_fields
    ))
    selected = result.selected
    st.caption(
        f"复核区间：{selected.base_start.date().isoformat()} 至 "
        f"{selected.base_end.date().isoformat()}"
    )
    question = profile.review_question_yes if computer_result == "YES" else profile.review_question_no
    st.subheader(question)
    st.caption(profile.review_help)


if source == "本地样例":
    st.caption("带成交量和底部参考线的本地日K样例")
    symbols = tuple(fixture.symbol for fixture in load_fixtures())
    selected_symbol = st.selectbox("样例股票", symbols)
    fixture = load_fixture(selected_symbol)
    flat_base = detect_flat_base(ohlcv_frame_from_series(fixture))
    _render_diagnostics(flat_base)
    st.plotly_chart(
        build_candlestick_figure(fixture, flat_base=flat_base), width="stretch",
        config={"displayModeBar": True, "scrollZoom": True},
    )
else:
    st.caption("来自本地逐股票缓存的 Futu 前复权日K与成交量")
    cache_root = Path(os.getenv("PATTERN_FINDER_CACHE_ROOT", str(DEFAULT_CACHE_ROOT)))
    validation_path = Path(os.getenv("PATTERN_FINDER_VALIDATION_PATH", str(DEFAULT_VALIDATION_PATH)))
    legacy_path = Path(os.getenv("PATTERN_FINDER_LEGACY_VALIDATION_PATH", str(LEGACY_VALIDATION_PATH)))
    ledger_path = Path(os.getenv("PATTERN_FINDER_MIGRATION_LEDGER_PATH", str(DEFAULT_MIGRATION_LEDGER_PATH)))
    repository_root = Path(os.getenv("PATTERN_FINDER_REPOSITORY_ROOT", Path.cwd()))
    migrate_legacy_validations(
        legacy_path, validation_path, ledger_path, repository_root=repository_root
    )
    symbols = cached_symbols(cache_root)
    if not symbols:
        st.info("没有可用的本地 M3B 缓存，请先在今日扫描中明确执行刷新。")
        st.stop()
    selected_symbol = st.selectbox("缓存股票", symbols)
    try:
        entry = load_cache_entry(selected_symbol, cache_root=cache_root, as_of_utc=datetime.now(UTC))
    except Exception as error:
        st.error(f"缓存读取失败：{error}")
    else:
        if entry is None:
            st.info("该股票没有本地缓存，请在今日扫描中明确执行 Futu 刷新。")
        else:
            report = entry.quality
            if report.passed:
                st.success(f"数据质量：通过｜{entry.rows} 行｜最新交易日 {report.last_session.isoformat()}")
            else:
                issues = list(report.errors)
                if report.missing_sessions:
                    issues.append(f"缺少 {len(report.missing_sessions)} 个 XNYS 交易日")
                st.warning("数据质量：失败｜" + "；".join(issues))
            frame = _cached_frame(entry.path.as_posix(), entry.path.stat().st_mtime_ns)
            series = chart_series_from_frame(frame, selected_symbol, max_bars=150)
            flat_base = detect_flat_base(frame) if report.passed and len(frame) >= 120 else None
            _render_diagnostics(flat_base)
            st.plotly_chart(
                build_candlestick_figure(series, flat_base=flat_base), width="stretch",
                config={"displayModeBar": True, "scrollZoom": True},
            )
            if flat_base is not None:
                try:
                    history = _cached_validation_history(
                        validation_path.as_posix(),
                        validation_path.stat().st_mtime_ns if validation_path.exists() else 0,
                    )
                except ValidationStoreError as error:
                    history = ()
                    validation_store_ok = False
                    st.error(f"验证历史无效：{error}")
                else:
                    validation_store_ok = True
                review_input = flat_base_review_input(flat_base)
                scan_date = review_input.scan_as_of_date.isoformat()
                key = (selected_symbol, profile.pattern_type, flat_base.detector_version, scan_date)
                current = latest_validations(history).get(key)
                history_count = sum(record.key == key for record in history)
                if current is None:
                    st.caption("人工复核：未人工复核｜历史次数：0")
                else:
                    st.caption(
                        f"人工复核：{current.human_label}｜验证结论："
                        f"{VALIDATION_RESULT_LABELS[current.validation_result]}｜"
                        f"历史次数：{history_count}｜原因标签："
                        f"{', '.join(current.reason_tags) or '-'}｜备注：{current.note or '-'}"
                    )
                with st.form(f"pattern_review_{profile.pattern_type}_{selected_symbol}", clear_on_submit=True):
                    human_label = st.segmented_control(
                        f"针对{profile.display_name_zh}的人工判断",
                        HUMAN_LABELS, default=None, required=True,
                        key=f"human_label_{profile.pattern_type}_{selected_symbol}",
                    )
                    reason_tags = st.pills(
                        f"{profile.display_name_zh}原因标签", profile.reason_tags,
                        selection_mode="multi", disabled=human_label == "像",
                        key=f"reason_tags_{profile.pattern_type}_{selected_symbol}",
                    )
                    note = st.text_area("备注", max_chars=MAX_NOTE_LENGTH, key=f"human_note_{selected_symbol}")
                    submitted = st.form_submit_button(
                        "保存人工复核", icon=":material/save:", disabled=not validation_store_ok
                    )
                if submitted and human_label is not None:
                    try:
                        record = build_pattern_validation(
                            recorded_at_utc=datetime.now(UTC), symbol=selected_symbol,
                            pattern_type=profile.pattern_type,
                            detector_version=review_input.detector_version,
                            scan_as_of_date=review_input.scan_as_of_date,
                            computer_result=review_input.computer_result,
                            human_label=human_label,
                            reason_tags=() if human_label == "像" else tuple(reason_tags or ()),
                            note=note or "", review_window_start=review_input.review_window_start,
                            review_window_end=review_input.review_window_end,
                            diagnostics=review_input.diagnostics,
                        )
                    except ValueError as error:
                        st.error(f"人工复核未保存：{error}")
                    else:
                        append_validation(validation_path, record)
                        st.cache_data.clear()
                        st.success(f"人工复核已保存：{VALIDATION_RESULT_LABELS[record.validation_result]}")
