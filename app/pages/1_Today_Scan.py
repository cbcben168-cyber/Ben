import os
from datetime import UTC, datetime
from pathlib import Path
import subprocess
from uuid import UUID

import pandas as pd
import streamlit as st

from tv_quant.pattern_finder.cache import DEFAULT_CACHE_ROOT, cached_symbols, flat_base_scan_rows
from tv_quant.pattern_finder.flat_base import detect_flat_base
from tv_quant.pattern_finder.fixtures import load_fixtures
from tv_quant.pattern_finder.futu_service import (
    refresh_pilot_universe,
    refresh_symbols,
    stale_cached_symbols,
)
from tv_quant.pattern_finder.models import ohlcv_frame_from_series
from tv_quant.pattern_finder.pattern_registry import enabled_pattern_profiles
from tv_quant.pattern_finder import review
from tv_quant.pattern_finder import validation
from tv_quant.pattern_finder.application import scan_persistence
from tv_quant.pattern_finder.persistence import (
    ScanRepository,
    SnapshotRepository,
    SqliteDatabase,
)
from tv_quant.pattern_finder.runtime.config import RuntimeConfig
from tv_quant.pattern_finder.universe_foundation import Completeness, SnapshotKind


st.set_page_config(page_title="今日扫描", page_icon="📋", layout="wide")
st.title("今日扫描")
profiles = enabled_pattern_profiles()
profile_names = tuple(profile.display_name_zh for profile in profiles)
selected_profile_name = st.selectbox("当前查看形态", profile_names)
profile = next(item for item in profiles if item.display_name_zh == selected_profile_name)
source = st.segmented_control(
    "数据来源", ("本地样例", "缓存 / Futu"), default="本地样例", required=True,
    key="today_scan_source",
)


@st.cache_data(ttl="30s", max_entries=8, show_spinner=False)
def _cached_scan(cache_root: str, as_of_iso: str, symbols: tuple[str, ...]):
    return flat_base_scan_rows(cache_root, datetime.fromisoformat(as_of_iso), symbols=symbols)


@st.cache_data(ttl="30s", max_entries=8, show_spinner=False)
def _cached_validation_history(path: str, modified_ns: int):
    del modified_ns
    return validation.read_validation_history(path)


def _git_commit(repository_root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repository_root,
            text=True,
            timeout=3,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _render_formal_scan_creation(cache_root: Path, repository_root: Path) -> None:
    try:
        config = RuntimeConfig.from_environment(repository_root)
    except (OSError, ValueError) as error:
        st.info(
            "需要正式且完整的 Universe Snapshot 才能保存正式扫描批次。"
            f"当前运行配置不可用：{error}"
        )
        return
    database = SqliteDatabase(config.database_path)
    snapshots = SnapshotRepository(database)
    try:
        summary = snapshots.latest_summary()
    except Exception as error:
        st.info(
            "需要正式且完整的 Universe Snapshot 才能保存正式扫描批次。"
            f"当前无法读取 Snapshot：{error}"
        )
        return

    if (
        summary is None
        or summary["snapshot_kind"] != SnapshotKind.FORMAL.value
        or summary["completeness"] != Completeness.COMPLETE.value
    ):
        st.info("需要正式且完整的 Universe Snapshot 才能保存正式扫描批次。")
        return

    try:
        snapshot = snapshots.get(UUID(str(summary["snapshot_id"])))
    except Exception as error:
        st.error(f"正式 Universe Snapshot 无法验证：{error}")
        return

    st.caption(
        "正式扫描来源："
        f"{snapshot.header.universe_snapshot_id}｜"
        f"{snapshot.header.as_of_session.isoformat()}｜"
        f"MEMBER {snapshot.header.member_count}"
    )
    if not st.button("保存正式扫描批次", type="primary"):
        return

    try:
        batch = scan_persistence.build_flat_base_scan(
            snapshot,
            cache_root=cache_root,
            completed_at_utc=datetime.now(UTC),
            code_commit=_git_commit(config.repository_root),
        )
        persisted = ScanRepository(database).append_completed(batch)
    except Exception as error:
        st.error(f"正式扫描批次保存失败：{error}")
        return

    manifest = persisted.manifest
    st.success(f"正式扫描批次已保存：{persisted.scan_batch_id}")
    st.caption(
        f"输入 {manifest.ordered_input_count}｜"
        f"数据通过 {manifest.quality_pass_count}｜"
        f"数据阻塞 {manifest.quality_fail_count}｜"
        f"YES {manifest.yes_count}｜NO {manifest.no_count}"
    )


if source == "本地样例":
    st.caption("确定性的本地样例数据")
    rows = []
    for fixture in load_fixtures():
        result = detect_flat_base(ohlcv_frame_from_series(fixture))
        selected = result.selected
        rows.append({
            "Symbol": fixture.symbol,
            "Pattern": fixture.pattern_label,
            "Bars": len(fixture.bars),
            "Flat Base": "是" if result.pattern_flat_base else "否",
            "Base Length": selected.base_length,
            "Base Depth": selected.base_depth_pct,
            "Bottom Tests": selected.bottom_test_count,
            "Normalized Slope": selected.normalized_slope,
            "Support": selected.support_level,
            "Resistance": selected.resistance_level,
        })
    fixture_columns = {
        "Symbol": "股票代码", "Pattern": "样例名称", "Bars": "K线数量",
        "Flat Base": "平底形态", "Base Length": "底部周期",
        "Base Depth": "底部深度", "Bottom Tests": "底部测试次数",
        "Normalized Slope": "标准化斜率", "Support": "支撑位",
        "Resistance": "阻力位",
    }
    st.dataframe(pd.DataFrame(rows).rename(columns=fixture_columns), hide_index=True, width="stretch")
else:
    cache_root = Path(os.getenv("PATTERN_FINDER_CACHE_ROOT", str(DEFAULT_CACHE_ROOT)))
    as_of = review.resolve_review_as_of_utc(
        os.getenv("PATTERN_FINDER_AS_OF_UTC")
    ).replace(second=0, microsecond=0)
    st.caption(f"试点缓存：{cache_root}｜日线｜前复权｜XNYS")
    try:
        stale_symbols = stale_cached_symbols(
            cache_root=cache_root,
            as_of_utc=as_of,
        )
    except Exception as error:
        stale_symbols = ()
        st.warning(f"无法检查过期缓存：{error}")

    if stale_symbols:
        st.caption(f"检测到 {len(stale_symbols)} 只过期缓存：{', '.join(stale_symbols)}")
        if st.button(
            f"刷新 {len(stale_symbols)} 只过期缓存",
            icon=":material/update:",
        ):
            try:
                with st.spinner("正在从 Futu OpenD 更新过期缓存……"):
                    entries = refresh_symbols(
                        stale_symbols,
                        cache_root=cache_root,
                        as_of_utc=datetime.now(UTC),
                    )
            except Exception as error:
                st.error(f"过期缓存刷新失败：{error}")
            else:
                st.cache_data.clear()
                st.success(f"已更新 {len(entries)} 只过期缓存。")
    else:
        st.caption("当前缓存没有检测到过期数据。")

    if st.button("从 Futu OpenD 刷新试点数据", icon=":material/refresh:", type="primary"):
        try:
            with st.spinner("正在从 Futu OpenD 更新试点股票……"):
                entries = refresh_pilot_universe(cache_root=cache_root, as_of_utc=datetime.now(UTC))
        except Exception as error:
            st.error(f"Futu 刷新失败：{error}")
        else:
            st.cache_data.clear()
            st.success(f"已更新 {len(entries)} 只试点股票。")

    validation_path = Path(os.getenv("PATTERN_FINDER_VALIDATION_PATH", str(validation.DEFAULT_VALIDATION_PATH)))
    legacy_path = Path(os.getenv("PATTERN_FINDER_LEGACY_VALIDATION_PATH", str(validation.LEGACY_VALIDATION_PATH)))
    ledger_path = Path(os.getenv("PATTERN_FINDER_MIGRATION_LEDGER_PATH", str(validation.DEFAULT_MIGRATION_LEDGER_PATH)))
    repository_root = Path(os.getenv("PATTERN_FINDER_REPOSITORY_ROOT", Path.cwd()))
    validation.migrate_legacy_validations(
        legacy_path, validation_path, ledger_path, repository_root=repository_root
    )
    symbols = cached_symbols(cache_root)
    rows = _cached_scan(cache_root.as_posix(), as_of.isoformat(), symbols)
    history = _cached_validation_history(
        validation_path.as_posix(),
        validation_path.stat().st_mtime_ns if validation_path.exists() else 0,
    )
    computer_filter = st.selectbox("电脑判断", review.COMPUTER_FILTERS)
    human_filter = st.selectbox("人工复核", review.HUMAN_FILTERS)
    validation_filter = st.selectbox("验证结论", review.VALIDATION_FILTERS)
    rows = review.filter_review_rows(
        review.attach_latest_validations(
            rows, history, pattern_type=profile.pattern_type,
            computer_result_field="Flat Base", scan_date_field="Base End",
        ),
        computer_filter=computer_filter, human_filter=human_filter,
        validation_filter=validation_filter,
    )
    columns = (
        "Symbol", "Flat Base", "Detector Version", "Base End", "Base Length",
        "Base Depth", "Bottom Tests", "Normalized Slope", "Human Label",
        "Validation Result", "Reason Tags", "Human Note", "Validation History Count",
        "Rows", "Data Quality", "Issues", "Adjustment",
    )
    display_names = {
        "Symbol": "股票代码", "Flat Base": "平底形态", "Detector Version": "检测器版本",
        "Base End": "扫描截止日", "Base Length": "底部周期", "Base Depth": "底部深度",
        "Bottom Tests": "底部测试次数", "Normalized Slope": "标准化斜率",
        "Human Label": "人工形态判断", "Validation Result": "验证结论",
        "Reason Tags": "原因标签", "Human Note": "人工备注",
        "Validation History Count": "历史复核次数", "Rows": "数据行数",
        "Data Quality": "数据质量", "Issues": "问题", "Adjustment": "复权方式",
    }
    table = pd.DataFrame(rows, columns=columns).rename(columns=display_names)
    table["平底形态"] = table["平底形态"].map({"YES": "是", "NO": "否"})
    st.dataframe(
        table,
        column_config={
            "底部深度": st.column_config.NumberColumn(format="%.4f"),
            "标准化斜率": st.column_config.NumberColumn(format="%.6f"),
        },
        hide_index=True,
        width="stretch",
    )
    _render_formal_scan_creation(cache_root, repository_root)
