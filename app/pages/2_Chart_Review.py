import os
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

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
from tv_quant.pattern_finder.pattern_registry import enabled_pattern_profiles
from tv_quant.pattern_finder import review
from tv_quant.pattern_finder import validation
from tv_quant.pattern_finder.application.review_queue import (
    QueueAction,
    QueueActionType,
    QueueCursor,
    QueueFilters,
    QueueState,
    move_visible,
    next_unreviewed,
    project_queue,
)
from tv_quant.pattern_finder.application.review_sources import (
    build_cache_queue_source,
    build_scan_batch_queue_source,
)
from tv_quant.pattern_finder.persistence import (
    ReviewQueueRepository,
    ScanRepository,
    SqliteDatabase,
)
from tv_quant.pattern_finder.runtime import RuntimeConfig


st.set_page_config(page_title="图表复核", page_icon="🕯️", layout="wide")
st.title("图表复核")
profiles = enabled_pattern_profiles()
profile_names = tuple(profile.display_name_zh for profile in profiles)
selected_profile_name = st.selectbox("当前查看形态", profile_names)
profile = next(item for item in profiles if item.display_name_zh == selected_profile_name)
st.caption(f"当前评价形态：{profile.display_name_zh}")
repository_root = Path(os.getenv("PATTERN_FINDER_REPOSITORY_ROOT", Path.cwd()))
try:
    runtime_config = RuntimeConfig.from_environment(repository_root)
    discovery_database = SqliteDatabase(runtime_config.database_path, read_only=True)
    discovery_database.validate_schema()
    completed_batches = ScanRepository(discovery_database).list_completed()
except Exception:
    runtime_config = None
    completed_batches = ()
source_options = (
    ("正式扫描批次", "缓存兼容", "本地样例")
    if completed_batches
    else ("本地样例", "缓存兼容")
)
source = st.segmented_control(
    "数据来源", source_options, default=source_options[0], required=True,
    key="chart_review_source",
)


@st.cache_data(ttl="30s", max_entries=16, show_spinner=False)
def _cached_frame(path: str, modified_ns: int):
    del modified_ns
    return load_standardized_csv(Path(path))[0]


@st.cache_data(ttl="30s", max_entries=8, show_spinner=False)
def _cached_validation_history(path: str, modified_ns: int):
    del modified_ns
    return validation.read_validation_history(path)


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
    review_input = review.flat_base_review_input(result)
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
    formal_mode = source == "正式扫描批次"
    st.caption(
        "来自不可变正式扫描批次的 Futu 前复权日K"
        if formal_mode
        else "来自本地逐股票缓存的 Futu 前复权日K与成交量"
    )
    cache_root = Path(os.getenv("PATTERN_FINDER_CACHE_ROOT", str(DEFAULT_CACHE_ROOT)))
    validation_path = Path(os.getenv("PATTERN_FINDER_VALIDATION_PATH", str(validation.DEFAULT_VALIDATION_PATH)))
    legacy_path = Path(os.getenv("PATTERN_FINDER_LEGACY_VALIDATION_PATH", str(validation.LEGACY_VALIDATION_PATH)))
    ledger_path = Path(os.getenv("PATTERN_FINDER_MIGRATION_LEDGER_PATH", str(validation.DEFAULT_MIGRATION_LEDGER_PATH)))
    validation.migrate_legacy_validations(
        legacy_path, validation_path, ledger_path, repository_root=repository_root
    )
    if not formal_mode and not cached_symbols(cache_root):
        st.info("没有可用的本地 M3B 缓存，请先在今日扫描中明确执行刷新。")
        st.stop()

    try:
        history = _cached_validation_history(
            validation_path.as_posix(),
            validation_path.stat().st_mtime_ns if validation_path.exists() else 0,
        )
    except validation.ValidationStoreError as error:
        history = ()
        validation_store_ok = False
        st.error(f"验证历史无效：{error}")
    else:
        validation_store_ok = True

    as_of_utc = review.resolve_review_as_of_utc(
        os.getenv("PATTERN_FINDER_AS_OF_UTC")
    )
    try:
        runtime_config = runtime_config or RuntimeConfig.from_environment(repository_root)
        database = SqliteDatabase(runtime_config.database_path)
        database.migrate()
        scans = ScanRepository(database)
        selected_batch = None
        if formal_mode:
            batches = scans.list_completed()
            if not batches:
                raise ValueError("没有已完成的正式扫描批次")
            batch_ids = tuple(batch.scan_batch_id for batch in batches)
            selected_batch_id = st.selectbox("正式扫描批次", batch_ids)
            selected_batch = next(
                batch for batch in batches if batch.scan_batch_id == selected_batch_id
            )
            queue_source = build_scan_batch_queue_source(selected_batch, history)
        else:
            queue_source = build_cache_queue_source(
                cache_root,
                as_of_utc,
                profile.pattern_type,
                history,
            )
        queue_repository = ReviewQueueRepository(database)
        latest_actions = queue_repository.latest_actions(
            queue_source.source_kind,
            queue_source.source_id,
            profile.pattern_type,
        )
        cursor = queue_repository.load_cursor(
            queue_source.source_kind,
            queue_source.source_id,
            profile.pattern_type,
        )
    except (OSError, RuntimeError, ValueError) as error:
        st.error(f"复核队列无法载入：{error}")
        st.stop()

    if selected_batch is None:
        st.warning(queue_source.label)
    else:
        manifest = selected_batch.manifest
        st.success(queue_source.label)
        st.caption(
            f"Batch {selected_batch.scan_batch_id}｜Snapshot {selected_batch.snapshot_id}｜"
            f"Profile {selected_batch.profile_version_id}｜"
            f"Detector {selected_batch.pattern_version}｜"
            f"Scan date {manifest.scan_as_of_date}"
        )
        st.caption(
            f"输入 {manifest.ordered_input_count}｜数据通过 {manifest.quality_pass_count}｜"
            f"数据阻塞 {manifest.quality_fail_count}｜YES {manifest.yes_count}｜"
            f"NO {manifest.no_count}"
        )
    state_labels = {
        "全部": None,
        "未复核": QueueState.UNREVIEWED,
        "已复核": QueueState.REVIEWED,
        "已跳过": QueueState.SKIPPED,
        "稍后处理": QueueState.SNOOZED,
        "数据阻塞": QueueState.DATA_BLOCKED,
    }
    stored_filters = cursor.filters if cursor is not None else QueueFilters()
    stored_state_label = next(
        label
        for label, state in state_labels.items()
        if state is stored_filters.state
    )
    selected_state_label = st.selectbox(
        "状态筛选",
        tuple(state_labels),
        index=tuple(state_labels).index(stored_state_label),
        key=f"queue_state_{queue_source.source_id}",
    )
    symbol_query = st.text_input(
        "精确股票代码",
        value=stored_filters.symbol_query,
        key=f"queue_symbol_{queue_source.source_id}",
    )
    filters = QueueFilters(
        state=state_labels[selected_state_label],
        symbol_query=symbol_query,
    )
    queue_items = queue_source.items
    if formal_mode:
        computer_filter = st.selectbox(
            "电脑判断", ("全部", "YES", "NO", "NOT_EVALUATED")
        )
        quality_filter = st.selectbox("数据质量", ("全部", "通过", "阻塞"))
        queue_items = tuple(
            item
            for item in queue_items
            if (
                computer_filter == "全部"
                or item.computer_decision == computer_filter
            )
            and (
                quality_filter == "全部"
                or item.data_quality_passed == (quality_filter == "通过")
            )
        )
    queue_view = project_queue(
        queue_items,
        latest_actions,
        filters,
        cursor.item_id if cursor is not None else None,
    )
    counts = queue_view.counts
    st.caption(
        "未复核 {0}｜已复核 {1}｜已跳过 {2}｜稍后处理 {3}｜数据阻塞 {4}".format(
            counts.unreviewed,
            counts.reviewed,
            counts.skipped,
            counts.snoozed,
            counts.data_blocked,
        )
    )
    if not queue_view.rows or queue_view.selected_item_id is None:
        st.info("当前筛选条件下没有可复核股票。")
        if cursor is not None and cursor.filters != filters:
            queue_repository.save_cursor(
                replace(cursor, filters=filters, updated_at_utc=datetime.now(UTC))
            )
        st.stop()

    selected_item = next(
        item
        for item in queue_view.rows
        if item.item_id == queue_view.selected_item_id
    )
    selected_position = next(
        index
        for index, item in enumerate(queue_view.rows, start=1)
        if item.item_id == selected_item.item_id
    )
    st.subheader(
        f"{selected_item.symbol} · {selected_position} / {len(queue_view.rows)}"
    )

    previous_column, next_column, skip_column, snooze_column, restore_column = (
        st.columns(5)
    )
    previous_clicked = previous_column.button("上一只", disabled=selected_position == 1)
    next_clicked = next_column.button(
        "下一只", disabled=selected_position == len(queue_view.rows)
    )
    selected_state = queue_view.states[selected_item.item_id]
    workflow_disabled = selected_state in {QueueState.REVIEWED, QueueState.DATA_BLOCKED}
    skip_clicked = skip_column.button("跳过", disabled=workflow_disabled)
    snooze_clicked = snooze_column.button("稍后处理", disabled=workflow_disabled)
    restore_clicked = restore_column.button(
        "恢复",
        disabled=selected_state not in {QueueState.SKIPPED, QueueState.SNOOZED},
    )

    def save_cursor(item_id: str) -> None:
        queue_repository.save_cursor(
            QueueCursor(
                source_kind=queue_source.source_kind,
                source_id=queue_source.source_id,
                pattern_type=profile.pattern_type,
                item_id=item_id,
                filters=filters,
                updated_at_utc=datetime.now(UTC),
            )
        )

    if previous_clicked or next_clicked:
        offset = -1 if previous_clicked else 1
        save_cursor(move_visible(queue_view, selected_item.item_id, offset))
        st.rerun()

    action_type = None
    if skip_clicked:
        action_type = QueueActionType.SKIP
    elif snooze_clicked:
        action_type = QueueActionType.SNOOZE
    elif restore_clicked:
        action_type = QueueActionType.RESTORE
    if action_type is not None:
        try:
            queue_repository.append_action(
                QueueAction(
                    action_id=str(uuid4()),
                    source_kind=queue_source.source_kind,
                    source_id=queue_source.source_id,
                    item_id=selected_item.item_id,
                    pattern_type=profile.pattern_type,
                    action_type=action_type,
                    created_at_utc=datetime.now(UTC),
                )
            )
            destination = next_unreviewed(queue_view, selected_item.item_id)
            save_cursor(destination or selected_item.item_id)
        except (OSError, RuntimeError, ValueError) as error:
            st.error(f"队列操作未保存：{error}")
        else:
            st.rerun()

    if cursor is None or cursor.item_id != selected_item.item_id or cursor.filters != filters:
        save_cursor(selected_item.item_id)

    selected_symbol = selected_item.symbol
    review_input = None
    if formal_mode:
        assert selected_batch is not None
        selected_result = next(
            result
            for result in selected_batch.results
            if result.candidate_id == selected_item.item_id
        )
        if not selected_item.data_quality_passed:
            st.warning(
                "DATA_BLOCKED｜正式扫描未评估｜原因："
                + (selected_item.quality_reason or "UNKNOWN")
            )
        else:
            features = selected_result.features
            diagnostics = {
                "base_length": int(features["base_length"]),
                "base_depth": float(features["base_depth_pct"]),
                "bottom_tests": int(features["bottom_test_count"]),
                "normalized_slope": float(features["normalized_slope"]),
                "support": float(features["support_level"]),
                "resistance": float(features["resistance_level"]),
            }
            review_input = review.PatternReviewInput(
                computer_result=selected_result.computer_decision.value,
                detector_version=selected_result.pattern_version,
                scan_as_of_date=date.fromisoformat(selected_result.signal_date),
                review_window_start=date.fromisoformat(str(features["base_start"])),
                review_window_end=date.fromisoformat(str(features["base_end"])),
                diagnostics=diagnostics,
            )
            st.success("数据质量：正式扫描时已通过")
            st.caption(
                f"电脑判断：{'是' if review_input.computer_result == 'YES' else '否'}｜"
                f"检测器版本：{review_input.detector_version}"
            )
            st.caption(
                "｜".join(
                    f"{field.display_name_zh}："
                    f"{_format_diagnostic(diagnostics[field.key], field.format_spec)}"
                    for field in profile.diagnostic_fields
                )
            )
            st.caption(
                f"复核区间：{review_input.review_window_start.isoformat()} 至 "
                f"{review_input.review_window_end.isoformat()}"
            )
            question = (
                profile.review_question_yes
                if review_input.computer_result == "YES"
                else profile.review_question_no
            )
            st.subheader(question)
            st.caption(profile.review_help)
            path = cache_root / f"{selected_symbol}_daily.csv"
            try:
                frame = _cached_frame(path.as_posix(), path.stat().st_mtime_ns)
            except (OSError, ValueError) as error:
                review_input = None
                st.warning(f"正式结果仍保留，但图表缓存当前不可用：{error}")
            else:
                series = chart_series_from_frame(frame, selected_symbol, max_bars=150)
                st.plotly_chart(
                    build_candlestick_figure(series),
                    width="stretch",
                    config={"displayModeBar": True, "scrollZoom": True},
                )
    else:
        try:
            entry = load_cache_entry(
                selected_symbol,
                cache_root=cache_root,
                as_of_utc=as_of_utc,
            )
        except Exception as error:
            st.error(f"缓存读取失败：{error}")
            st.stop()
        if entry is None:
            st.info("该股票没有本地缓存，请在今日扫描中明确执行 Futu 刷新。")
            st.stop()

        report = entry.quality
        if report.passed:
            st.success(
                f"数据质量：通过｜{entry.rows} 行｜"
                f"最新交易日 {report.last_session.isoformat()}"
            )
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
            review_input = review.flat_base_review_input(flat_base)

    if review_input is not None:
        scan_date = review_input.scan_as_of_date.isoformat()
        key = (
            selected_symbol,
            profile.pattern_type,
            review_input.detector_version,
            scan_date,
        )
        current = validation.latest_validations(history).get(key)
        history_count = sum(record.key == key for record in history)
        if current is None:
            st.caption("人工复核：未人工复核｜历史次数：0")
        else:
            st.caption(
                f"人工复核：{current.human_label}｜验证结论："
                f"{validation.VALIDATION_RESULT_LABELS[current.validation_result]}｜"
                f"历史次数：{history_count}｜原因标签："
                f"{', '.join(current.reason_tags) or '-'}｜备注：{current.note or '-'}"
            )
        with st.form(f"pattern_review_{profile.pattern_type}_{selected_item.item_id}"):
            human_label = st.segmented_control(
                f"针对{profile.display_name_zh}的人工判断",
                validation.HUMAN_LABELS, default=None, required=True,
                key=f"human_label_{profile.pattern_type}_{selected_item.item_id}",
            )
            reason_tags = st.pills(
                f"{profile.display_name_zh}原因标签", profile.reason_tags,
                selection_mode="multi", disabled=human_label == "像",
                key=f"reason_tags_{profile.pattern_type}_{selected_item.item_id}",
            )
            note = st.text_area(
                "备注",
                max_chars=validation.MAX_NOTE_LENGTH,
                key=f"human_note_{selected_item.item_id}",
            )
            save_and_next = st.form_submit_button(
                "保存并下一只",
                icon=":material/save:",
                disabled=not validation_store_ok,
            )
            save_only = st.form_submit_button(
                "仅保存",
                disabled=not validation_store_ok,
            )
        if (save_and_next or save_only) and human_label is not None:
            submission_key = (
                f"review_submission_{queue_source.source_id}_{selected_item.item_id}"
            )
            submission_id = st.session_state.setdefault(submission_key, str(uuid4()))
            try:
                record = validation.build_pattern_validation(
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
                    submission_id=submission_id,
                )
                validation.append_validation(validation_path, record)
            except (OSError, ValueError, validation.ValidationStoreError) as error:
                st.error(f"人工复核未保存：{error}")
            else:
                destination = (
                    next_unreviewed(queue_view, selected_item.item_id)
                    if save_and_next
                    else selected_item.item_id
                )
                try:
                    save_cursor(destination or selected_item.item_id)
                except (OSError, RuntimeError) as error:
                    st.error(f"人工复核已保存，但队列位置未更新：{error}")
                else:
                    st.session_state[submission_key] = str(uuid4())
                    st.cache_data.clear()
                    st.session_state["chart_review_flash"] = (
                        "人工复核已保存："
                        + validation.VALIDATION_RESULT_LABELS[record.validation_result]
                    )
                    st.rerun()

    flash = st.session_state.pop("chart_review_flash", None)
    if flash:
        st.success(flash)

    st.dataframe(
        [
            {
                "股票代码": item.symbol,
                "状态": queue_view.states[item.item_id].value,
                "数据质量": "通过" if item.data_quality_passed else "阻塞",
            }
            for item in queue_view.rows
        ],
        width="stretch",
        hide_index=True,
    )
