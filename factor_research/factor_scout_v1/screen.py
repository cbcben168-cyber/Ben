from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .core import (
    EVIDENCE_LABEL,
    FACTORS,
    PRICE_COLUMNS,
    TRAIN_EVIDENCE_LABEL,
    RunCounters,
    ScoutBlocked,
    load_registry,
    run_screen,
)

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
TRAIN_RUN_ID = "FACTOR_SCOUT_V1_TRAIN_SCREEN_20261016_01"
TRAIN_STAGE = "TRAIN_EXPLORATORY_SCREEN_ONLY"
TRAIN_START = "2025-10-01"
TRAIN_END = "2026-06-30"
TRAIN_SESSIONS = 187
TRAIN_BARS = 14_514
TRAIN_INPUT_DIR = (
    REPO_ROOT
    / "factor_research"
    / "spy_factor_batch_v1"
    / "validation"
    / "train_ema_supplement_7514881494081894629"
)
TRAIN_DATA_PATH = TRAIN_INPUT_DIR / "opend_5m_ohlc.csv"
TRAIN_REHAB_PATH = TRAIN_INPUT_DIR / "opend_rehab.csv"
TRAIN_MANIFEST_PATH = TRAIN_INPUT_DIR / "manifest.json"
TRAIN_OUTPUT_DIR = ROOT / "outputs" / "runs" / TRAIN_RUN_ID
EXPECTED_INPUT_HASHES = {
    "ohlc": "e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f",
    "rehab": "16a1bae16d562edffac364cbba2a6a26d72765e1eca57ab0c31189b37ceb17c4",
    "manifest": "f1f750867dd4a32eaf74d4d776dcf47002f0aa7f5b123db4177e57c4a1a266da",
}
PIT_STATUS = "PIT_APPROXIMATION_UNVERIFIED"
XNYS_HOLIDAYS = frozenset(
    {
        "2025-11-27",
        "2025-12-25",
        "2026-01-01",
        "2026-01-19",
        "2026-02-16",
        "2026-04-03",
        "2026-05-25",
        "2026-06-19",
    }
)
XNYS_EARLY_CLOSES = frozenset({"2025-11-28", "2025-12-24"})


def build_synthetic_ohlc(session_count: int = 26) -> pd.DataFrame:
    """Create deterministic, manually specified 5-minute RTH OHLC for Phase A only."""
    rows: list[dict[str, object]] = []
    sessions = pd.bdate_range("2024-01-02", periods=session_count)
    previous_close = 100.0
    for day_number, day in enumerate(sessions):
        local_times = pd.date_range(
            f"{day.date()} 09:35", periods=78, freq="5min", tz="America/New_York"
        )
        day_bias = ((day_number % 5) - 2) * 0.012
        price = previous_close + ((day_number % 3) - 1) * 0.08
        for bar_number, local_time in enumerate(local_times):
            opening = price
            increment = day_bias + 0.025 * np.sin((bar_number + day_number) / 5.0)
            if day_number >= 20 and bar_number < 6:
                increment += 0.08 if day_number % 2 == 0 else -0.08
            closing = opening + increment
            high = max(opening, closing) + 0.035 + 0.003 * (bar_number % 3)
            low = min(opening, closing) - 0.035 - 0.002 * (bar_number % 2)
            timestamp = local_time.tz_convert("UTC")
            rows.append(
                {
                    "timestamp_utc": timestamp,
                    "bar_available_at_utc": timestamp,
                    "session_date": day.strftime("%Y-%m-%d"),
                    "open": opening,
                    "high": high,
                    "low": low,
                    "close": closing,
                    "pit_status": "PIT_VERIFIED",
                    "session_complete": True,
                }
            )
            price = closing
        previous_close = price
    return pd.DataFrame(rows)


def _frame_sha256(frame: pd.DataFrame) -> str:
    canonical = frame.copy()
    for column in ("timestamp_utc", "bar_available_at_utc"):
        canonical[column] = pd.to_datetime(canonical[column], utc=True).map(lambda value: value.isoformat())
    payload = canonical.to_csv(index=False, lineterminator="\n").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _xnys_schedule() -> tuple[dict[str, str], dict[str, pd.DatetimeIndex]]:
    sessions = [
        value.strftime("%Y-%m-%d")
        for value in pd.bdate_range(TRAIN_START, TRAIN_END)
        if value.strftime("%Y-%m-%d") not in XNYS_HOLIDAYS
    ]
    if len(sessions) != TRAIN_SESSIONS:
        raise ScoutBlocked("BLOCKED_DATA:XNYS_SESSION_COUNT_MISMATCH")
    closes: dict[str, str] = {}
    grids: dict[str, pd.DatetimeIndex] = {}
    for session_date in sessions:
        close_et = "13:00" if session_date in XNYS_EARLY_CLOSES else "16:00"
        closes[session_date] = close_et
        grids[session_date] = pd.date_range(
            f"{session_date} 09:35",
            f"{session_date} {close_et}",
            freq="5min",
            tz="America/New_York",
        ).tz_convert("UTC")
    if sum(len(grid) for grid in grids.values()) != TRAIN_BARS:
        raise ScoutBlocked("BLOCKED_DATA:XNYS_BAR_COUNT_MISMATCH")
    return closes, grids


def _validate_manifest_and_hashes() -> tuple[dict[str, object], dict[str, str]]:
    for path in (TRAIN_DATA_PATH, TRAIN_REHAB_PATH, TRAIN_MANIFEST_PATH):
        if not path.is_file():
            raise ScoutBlocked(f"BLOCKED_DATA:REQUIRED_INPUT_MISSING:{path.name}")
    hashes = {
        "ohlc": _file_sha256(TRAIN_DATA_PATH),
        "rehab": _file_sha256(TRAIN_REHAB_PATH),
        "manifest": _file_sha256(TRAIN_MANIFEST_PATH),
    }
    if hashes != EXPECTED_INPUT_HASHES:
        raise ScoutBlocked("BLOCKED_DATA:FROZEN_INPUT_HASH_MISMATCH")
    manifest = json.loads(TRAIN_MANIFEST_PATH.read_text(encoding="utf-8"))
    contract = manifest.get("query_contract", {})
    required = {
        "symbol": "US.SPY",
        "bar_type": "K_5M",
        "session": "RTH",
        "extended_time": False,
        "historical_autype": "NONE",
        "time_label": "America/New_York bar end",
        "end": TRAIN_END,
    }
    if any(contract.get(key) != value for key, value in required.items()):
        raise ScoutBlocked("BLOCKED_DATA:INPUT_MANIFEST_CONTRACT_MISMATCH")
    artifacts = manifest.get("artifacts", {})
    if artifacts.get(TRAIN_DATA_PATH.name, {}).get("sha256") != hashes["ohlc"]:
        raise ScoutBlocked("BLOCKED_DATA:OHLC_MANIFEST_IDENTITY_MISMATCH")
    if artifacts.get(TRAIN_REHAB_PATH.name, {}).get("sha256") != hashes["rehab"]:
        raise ScoutBlocked("BLOCKED_DATA:REHAB_MANIFEST_IDENTITY_MISMATCH")
    return manifest, hashes


def load_frozen_train() -> tuple[pd.DataFrame, dict[str, str], dict[str, object]]:
    manifest, hashes = _validate_manifest_and_hashes()
    raw = pd.read_csv(TRAIN_DATA_PATH, float_precision="round_trip")
    if tuple(raw.columns) != ("time_key", *PRICE_COLUMNS):
        raise ScoutBlocked("BLOCKED_DATA:RAW_OHLC_SCHEMA_MISMATCH")
    raw["time_key"] = pd.to_datetime(raw["time_key"], errors="raise")
    raw["session_date"] = raw["time_key"].dt.strftime("%Y-%m-%d")
    raw = raw.loc[raw["session_date"].between(TRAIN_START, TRAIN_END)].copy()
    if len(raw) != TRAIN_BARS or raw["session_date"].nunique() != TRAIN_SESSIONS:
        raise ScoutBlocked("BLOCKED_DATA:TRAIN_COVERAGE_MISMATCH")
    for column in PRICE_COLUMNS:
        raw[column] = pd.to_numeric(raw[column], errors="raise")
    numeric = raw.loc[:, PRICE_COLUMNS].to_numpy(float)
    if not np.isfinite(numeric).all() or (numeric <= 0).any():
        raise ScoutBlocked("BLOCKED_DATA:INVALID_RAW_OHLC")
    local = raw["time_key"].dt.tz_localize(
        "America/New_York", ambiguous="raise", nonexistent="raise"
    )
    raw["timestamp_utc"] = local.dt.tz_convert("UTC")

    session_closes, grids = _xnys_schedule()
    for session_date, expected in grids.items():
        actual = pd.DatetimeIndex(
            raw.loc[raw["session_date"].eq(session_date), "timestamp_utc"]
        )
        if not actual.equals(expected):
            raise ScoutBlocked(f"BLOCKED_DATA:XNYS_GRID_MISMATCH:{session_date}")

    rehab = pd.read_csv(TRAIN_REHAB_PATH)
    required_rehab = (
        "ex_div_date",
        "forward_adj_factor_a",
        "forward_adj_factor_b",
        "per_cash_div",
    )
    if tuple(rehab.columns) != required_rehab or rehab.empty:
        raise ScoutBlocked("BLOCKED_PIT:REHAB_SCHEMA_OR_CONTENT_MISMATCH")
    rehab["ex_div_date"] = pd.to_datetime(rehab["ex_div_date"], errors="raise").dt.strftime("%Y-%m-%d")
    if rehab["ex_div_date"].duplicated().any() or not rehab["ex_div_date"].is_monotonic_increasing:
        raise ScoutBlocked("BLOCKED_PIT:REHAB_DATE_IDENTITY_INVALID")
    adjusted = raw.copy()
    adjustment_audit: list[dict[str, object]] = []
    for event in rehab.itertuples(index=False):
        factor_a = float(event.forward_adj_factor_a)
        factor_b = float(event.forward_adj_factor_b)
        if not np.isfinite([factor_a, factor_b]).all() or factor_a <= 0:
            raise ScoutBlocked("BLOCKED_PIT:REHAB_FACTOR_INVALID")
        affected = adjusted["session_date"] < event.ex_div_date
        for column in PRICE_COLUMNS:
            adjusted.loc[affected, column] = factor_a * adjusted.loc[affected, column] + factor_b
        adjustment_audit.append(
            {"ex_div_date": event.ex_div_date, "affected_rows": int(affected.sum())}
        )

    adjusted["bar_available_at_utc"] = adjusted["timestamp_utc"]
    adjusted["pit_status"] = PIT_STATUS
    adjusted["session_complete"] = True
    prepared = adjusted.loc[
        :,
        [
            "timestamp_utc",
            "bar_available_at_utc",
            "session_date",
            *PRICE_COLUMNS,
            "pit_status",
            "session_complete",
        ],
    ]
    qualification: dict[str, object] = {
        "status": "DATA_GATE_PASS_EXPLORATORY_PIT_APPROXIMATION",
        "symbol": "US.SPY",
        "bar_size": "5m",
        "session": "XNYS_RTH",
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "train_sessions": TRAIN_SESSIONS,
        "train_bars": TRAIN_BARS,
        "source_price_basis": "AUTYPE_NONE_RAW",
        "analysis_price_basis": "FROZEN_RETROSPECTIVE_FINAL_BASIS_THROUGH_TRAIN_END",
        "pit_status": PIT_STATUS,
        "bar_availability_basis": "BAR_END_LABEL_AS_AVAILABILITY_PROXY",
        "confirmatory_use_allowed": False,
        "rehab_snapshot_generated_at_utc": manifest.get("generated_at_utc"),
        "rehab_events": adjustment_audit,
        "input_hashes": hashes,
        "validation_oos_accessed": False,
        "opend_accessed": False,
    }
    return prepared, session_closes, qualification


def render_report(results: pd.DataFrame, registry: pd.DataFrame, identity: dict[str, object]) -> str:
    status_counts = registry["status"].value_counts().to_dict()
    lines = [
        "# Factor Scout V1 Phase A 人工筛选报告",
        "",
        f"- 证据等级：`{EVIDENCE_LABEL}`",
        f"- 运行ID：`{identity['run_id']}`",
        f"- 人工OHLC SHA256：`{identity['input_sha256']}`",
        f"- 因子范围：{', '.join(f.factor_id for f in FACTORS)}",
        f"- 静态状态：REVIEW={status_counts.get('REVIEW', 0)}，WATCH={sum(v for k, v in status_counts.items() if k.startswith('WATCH'))}，BLOCKED={sum(v for k, v in status_counts.items() if k.startswith('BLOCKED'))}",
        "",
        "## 分类别功能结果",
        "",
        "以下数值仅用于核对计算链；方向类单位为bp，波动率/状态类为非年化实现波动率。不同类别不得混排。",
        "",
    ]
    for target_type in ("DIRECTION", "VOLATILITY", "STATE"):
        lines.append(f"### {target_type}")
        lines.append("")
        subset = results.loc[results["target_type"].eq(target_type)]
        if target_type != "STATE":
            subset = subset.sort_values("forward_mean", ascending=False, na_position="last")
        for row in subset.itertuples(index=False):
            mean_text = "NA" if pd.isna(row.forward_mean) else f"{row.forward_mean:.6f}"
            lines.append(
                f"- {row.factor_id}：events={row.events}，eligible={row.eligible_sessions}，forward_mean={mean_text}，`{row.screen_status}`"
            )
        lines.append("")
    lines.extend(
        [
            "## 限制与下一阶段门",
            "",
            "本次只有人工OHLC，筛选结果属于探索性功能观察，不能证明交易Edge；没有读取真实TRAIN、Validation/OOS，也没有计算订单、期权PnL或资金曲线。",
            "",
            "如需Phase B，必须另行明确授权真实TRAIN数据路径/读取方式、日期、Stage、Run ID和输出目录。",
            "",
            "本报告未产生任何验证Edge、样本外通过或实盘就绪结论。",
        ]
    )
    return "\n".join(lines) + "\n"


def render_train_report(results: pd.DataFrame, identity: dict[str, object]) -> str:
    counts = results["screen_status"].value_counts().to_dict()
    lines = [
        "# Factor Scout V1 TRAIN探索筛选报告",
        "",
        f"- 运行ID：`{identity['run_id']}`",
        f"- Stage：`{identity['stage']}`",
        f"- 证据等级：`{TRAIN_EVIDENCE_LABEL}`",
        f"- PIT状态：`{PIT_STATUS}`；禁止确认性用途。",
        f"- 数据：US.SPY，XNYS RTH，5分钟，{TRAIN_START} 至 {TRAIN_END}。",
        f"- 分类：KEEP={counts.get('KEEP_FOR_DEEP_TEST', 0)}，容量观察={counts.get('WATCH_CAPACITY', 0)}，不稳定={counts.get('WATCH_UNSTABLE', 0)}，重叠={counts.get('WATCH_OVERLAP', 0)}。",
        "",
        "## 六因子结果",
        "",
    ]
    for target_type in ("DIRECTION", "VOLATILITY", "STATE"):
        lines.extend([f"### {target_type}", ""])
        for row in results.loc[results["target_type"].eq(target_type)].itertuples(index=False):
            lift = "NA" if pd.isna(row.lift_vs_baseline) else f"{row.lift_vs_baseline:.6f}"
            lines.append(
                f"- {row.factor_id}：events={row.events}，days={row.unique_days}，lift={lift}，`{row.screen_status}`；{row.reason}。"
            )
        lines.append("")
    lines.extend(
        [
            "## 限制",
            "",
            "本次仅为TRAIN内部探索筛选；60/40两段均非OOS。复权事件缺少历史available_at证据，按effective date近似并保留PIT_APPROXIMATION_UNVERIFIED。未访问Validation/OOS、账户、持仓或订单。",
            "",
            "结果不构成Edge确认、交易策略回测、OOS通过或实盘就绪结论。",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(output_dir: Path) -> dict[str, object]:
    registry = load_registry(ROOT / "FACTOR_REGISTRY.csv")
    synthetic = build_synthetic_ohlc()
    counters = RunCounters()
    results, _observations = run_screen(synthetic, counters)
    run_id = "FACTOR_SCOUT_V1_PHASE_A_SYNTHETIC_DEMO_V1"
    identity: dict[str, object] = {
        "run_id": run_id,
        "evidence_label": EVIDENCE_LABEL,
        "input_kind": "MANUALLY_GENERATED_5M_OHLC",
        "input_sha256": _frame_sha256(synthetic),
        "row_count": int(len(synthetic)),
        "session_count": int(synthetic["session_date"].nunique()),
        "source_sha256": {
            "core.py": _file_sha256(ROOT / "core.py"),
            "screen.py": _file_sha256(ROOT / "screen.py"),
            "FACTOR_REGISTRY.csv": _file_sha256(ROOT / "FACTOR_REGISTRY.csv"),
        },
        "passes": {
            "data_reads": counters.data_reads,
            "feature_passes": counters.feature_passes,
            "forward_passes": counters.forward_passes,
        },
        "real_train_read": False,
        "validation_oos_read": False,
        "forbidden_labels_emitted": False,
    }
    shortlist = registry.loc[
        registry["decision"].eq("RETAIN"),
        ["factor_id", "name", "target_type", "status", "decision", "reason"],
    ].copy()
    shortlist.insert(0, "evidence_label", EVIDENCE_LABEL)
    shortlist["selection_basis"] = "STATIC_REVIEW_ONLY_NOT_MARKET_RESULT"
    output_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(output_dir / "FACTOR_SCREEN_RESULTS.csv", index=False, lineterminator="\n")
    shortlist.to_csv(output_dir / "FACTOR_SHORTLIST.csv", index=False, lineterminator="\n")
    (output_dir / "SCREEN_REPORT.md").write_text(
        render_report(results, registry, identity), encoding="utf-8", newline="\n"
    )
    (output_dir / "SCREEN_RUN_IDENTITY.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return identity


def write_train_outputs(output_dir: Path = TRAIN_OUTPUT_DIR) -> dict[str, object]:
    if output_dir.exists():
        raise ScoutBlocked(f"BLOCKED_DATA:OUTPUT_ALREADY_EXISTS:{output_dir}")
    registry = load_registry(ROOT / "FACTOR_REGISTRY.csv")
    train, session_closes, qualification = load_frozen_train()
    counters = RunCounters()
    results, _observations = run_screen(
        train,
        counters,
        session_close_by_date=session_closes,
        allowed_pit_statuses=frozenset({PIT_STATUS}),
        evidence_label=TRAIN_EVIDENCE_LABEL,
        pit_status=PIT_STATUS,
    )
    identity: dict[str, object] = {
        "run_id": TRAIN_RUN_ID,
        "stage": TRAIN_STAGE,
        "evidence_label": TRAIN_EVIDENCE_LABEL,
        "data_qualification": qualification,
        "factor_ids": [factor.factor_id for factor in FACTORS],
        "forward_contract": "NEXT_BAR_OPEN_TO_SIXTH_BAR_CLOSE_AND_UNANNUALIZED_RV",
        "baseline_contract": "SAME_ANCHOR_ALL_ELIGIBLE_AND_NO_SIGNAL",
        "stability_contract": "GLOBAL_CHRONOLOGICAL_60_40_TRAIN_INTERNAL",
        "capacity_contract": "EVENTS_GE_50_AND_UNIQUE_DAYS_GE_40_SCHEDULING_HINT",
        "passes": {
            "data_reads": counters.data_reads,
            "feature_passes": counters.feature_passes,
            "forward_passes": counters.forward_passes,
        },
        "source_sha256": {
            "core.py": _file_sha256(ROOT / "core.py"),
            "screen.py": _file_sha256(ROOT / "screen.py"),
            "FACTOR_REGISTRY.csv": _file_sha256(ROOT / "FACTOR_REGISTRY.csv"),
        },
        "real_train_read": True,
        "validation_oos_read": False,
        "opend_accessed": False,
        "confirmatory_use_allowed": False,
    }
    shortlist = results.loc[
        results["screen_status"].isin(
            {"KEEP_FOR_DEEP_TEST", "WATCH_CAPACITY", "WATCH_UNSTABLE", "WATCH_OVERLAP"}
        ),
        [
            "factor_id",
            "target_type",
            "events",
            "unique_days",
            "lift_vs_baseline",
            "early_lift",
            "late_lift",
            "screen_status",
            "reason",
        ],
    ].copy()
    shortlist.insert(0, "evidence_label", TRAIN_EVIDENCE_LABEL)
    output_dir.mkdir(parents=True, exist_ok=False)
    results.to_csv(output_dir / "FACTOR_SCREEN_RESULTS.csv", index=False, lineterminator="\n")
    shortlist.to_csv(output_dir / "FACTOR_SHORTLIST.csv", index=False, lineterminator="\n")
    (output_dir / "SCREEN_REPORT.md").write_text(
        render_train_report(results, identity), encoding="utf-8", newline="\n"
    )
    (output_dir / "SCREEN_RUN_IDENTITY.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    return identity


def main() -> int:
    parser = argparse.ArgumentParser(description="Factor Scout V1 gated screen runner")
    gate = parser.add_mutually_exclusive_group(required=True)
    gate.add_argument("--synthetic-demo", action="store_true", help="Phase A synthetic execution gate")
    gate.add_argument(
        "--authorize-train-screen",
        metavar="RUN_ID",
        help="exact Phase B one-shot authorization token",
    )
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()
    if args.synthetic_demo:
        identity = write_outputs(args.output_dir)
    else:
        if args.authorize_train_screen != TRAIN_RUN_ID:
            parser.error("Phase B requires the exact frozen Run ID")
        if args.output_dir != ROOT / "outputs":
            parser.error("Phase B output directory is frozen and cannot be overridden")
        identity = write_train_outputs()
    print(json.dumps(identity, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
