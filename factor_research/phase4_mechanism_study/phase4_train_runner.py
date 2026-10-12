from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

from .contracts import (
    BOOTSTRAP_ITERATIONS,
    FAMILY,
    PRIMARY_COST,
    ROBUSTNESS_COST,
    RULE_HASH_SHA256,
    SENSITIVITY_COST,
    TRAIN_SESSIONS,
    Phase4ContractError,
    load_and_verify_preregistration,
)
from .mechanisms import ScanResult, Signal, scan_all
from .overlap import OverlapResult, family_overlap, overlap_gate
from .run_phase4 import engine_code_hash
from .simulator import ReplayResult, replay_scan
from .statistics import StatisticsResult, evaluate_family
from .structural_preflight import (
    EXPECTED_AUDIT_MANIFEST_SHA256,
    EXPECTED_DATA_SHA256,
    EXPECTED_REHAB_SHA256,
    PHASE41_CODE_HASH,
    qualify_authorized_train,
)
from .volatility import QualifiedData

ATTEMPT_ID = "P4_TRAIN_V1_ONE_SHOT"
RUNNER_VERSION = "PHASE4_TRAIN_RUNNER_V1"
AUTHORIZATION_TOKEN = ATTEMPT_ID
PHASE42_COMMIT = "e6b8737f0cc5cbb7314a8f37e7e44be72d803ed6"
PHASE42_SOURCE_SHA256 = "d3edde168f4ac29c526c0a858dc713b681fb16fa8fdfc584a47d8928bfaf553d"
PHASE42_RESULT_SHA256 = "5aa17767486cc4d7025e0b88e2df8b5150b5b35a33a616a000ec3143e5e4d5ee"
OUTPUT_DIRECTORY = "outputs/phase4_train_v1"
REQUIRED_OUTPUTS = (
    "REPORT_CN.md",
    "STRATEGY_RESULTS.csv",
    "TRADE_LOG.csv",
    "SIGNAL_AUDIT.csv",
    "STATISTICS_GATE.json",
    "ROBUSTNESS_SUMMARY.csv",
    "TEST_REGISTRY.csv",
    "ATTEMPT_AUDIT.json",
    "PRE_REGISTRATION_SNAPSHOT.json",
)
TRADE_COLUMNS = (
    "trade_id",
    "hypothesis_id",
    "session_date",
    "signal_time_et",
    "direction",
    "direction_label",
    "entry_price",
    "stop_price",
    "target_price",
    "exit_reason_stop_first",
    "exit_price_stop_first",
    "exit_reason_target_first",
    "exit_price_target_first",
    "gross_return_stop_first",
    "net_return_2bp_stop_first",
    "net_return_4bp_stop_first",
    "net_return_6bp_stop_first",
    "gross_return_target_first",
    "net_return_2bp_target_first",
    "net_return_4bp_target_first",
    "net_return_6bp_target_first",
    "same_bar_dual_trigger",
)


class Phase4TrainError(Phase4ContractError):
    """A fail-closed Phase 4.3 execution or audit violation."""


@dataclass(frozen=True)
class ResearchBundle:
    signal_audit: pd.DataFrame
    trade_log: pd.DataFrame
    overlap: tuple[OverlapResult, ...]
    statistics: StatisticsResult


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _package_dir() -> Path:
    return Path(__file__).resolve().parent


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def runner_source_hash() -> str:
    return _sha256_file(Path(__file__).resolve())


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _json_text(payload: Any) -> str:
    return json.dumps(_json_ready(payload), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_text(path, _json_text(payload))


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    _atomic_text(path, frame.to_csv(index=False, lineterminator="\n"))


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=_repo_root(), check=True, capture_output=True, text=True
    ).stdout.strip()


def _git_is_clean_tracked() -> bool:
    unstaged = subprocess.run(["git", "diff", "--quiet"], cwd=_repo_root()).returncode
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=_repo_root()).returncode
    return unstaged == staged == 0


def _attempt_registered(registry_path: Path) -> bool:
    if not registry_path.is_file():
        return False
    with registry_path.open("r", encoding="utf-8", newline="") as handle:
        return any(row.get("attempt_id") == ATTEMPT_ID for row in csv.DictReader(handle))


def verify_train_identity(
    registration_path: Path | None = None,
    *,
    verify_git: bool = True,
    check_attempt: bool = True,
) -> dict[str, Any]:
    package = _package_dir()
    registration_file = registration_path or package / "train_registration.json"
    registration = json.loads(registration_file.read_text(encoding="utf-8"))
    expected = {
        "attempt_id": ATTEMPT_ID,
        "runner_version": RUNNER_VERSION,
        "phase42_commit": PHASE42_COMMIT,
        "phase41_rule_hash_sha256": RULE_HASH_SHA256,
        "phase41_code_hash_sha256": PHASE41_CODE_HASH,
        "phase42_preflight_source_sha256": PHASE42_SOURCE_SHA256,
        "phase42_result_sha256": PHASE42_RESULT_SHA256,
        "data_sha256": EXPECTED_DATA_SHA256,
        "audit_manifest_sha256": EXPECTED_AUDIT_MANIFEST_SHA256,
        "rehab_sha256": EXPECTED_REHAB_SHA256,
        "output_directory": OUTPUT_DIRECTORY,
        "family_id": "P4_PRIMARY_V1",
        "family_size": len(FAMILY),
        "real_run_limit": 1,
    }
    mismatches = [key for key, value in expected.items() if registration.get(key) != value]
    if mismatches:
        raise Phase4TrainError("TRAIN_REGISTRATION_MISMATCH:" + ",".join(mismatches))
    if tuple(registration.get("hypotheses", ())) != FAMILY:
        raise Phase4TrainError("INCOMPLETE_PRIMARY_FAMILY")
    if registration.get("runner_source_sha256") != runner_source_hash():
        raise Phase4TrainError("RUNNER_SOURCE_HASH_MISMATCH")
    synthetic_path = package / "synthetic_validation.json"
    if registration.get("synthetic_validation_sha256") != _sha256_file(synthetic_path):
        raise Phase4TrainError("SYNTHETIC_VALIDATION_HASH_MISMATCH")
    synthetic = json.loads(synthetic_path.read_text(encoding="utf-8"))
    if synthetic.get("status") != "PASS" or synthetic.get("real_train_accessed") is not False:
        raise Phase4TrainError("SYNTHETIC_VALIDATION_NOT_PASS")
    if not synthetic.get("checks") or any(item.get("status") != "PASS" for item in synthetic["checks"]):
        raise Phase4TrainError("SYNTHETIC_CHECK_INCOMPLETE")
    test_source = package / "tests" / "test_phase4_train_runner.py"
    if registration.get("test_source_sha256") != _sha256_file(test_source):
        raise Phase4TrainError("TRAIN_TEST_SOURCE_HASH_MISMATCH")

    preregistration = load_and_verify_preregistration()
    if engine_code_hash() != PHASE41_CODE_HASH:
        raise Phase4TrainError("PHASE41_ENGINE_HASH_MISMATCH")
    if preregistration.get("rule_hash_sha256") != RULE_HASH_SHA256:
        raise Phase4TrainError("PHASE41_RULE_HASH_MISMATCH")
    preflight_source = package / "structural_preflight.py"
    if _sha256_file(preflight_source) != PHASE42_SOURCE_SHA256:
        raise Phase4TrainError("PHASE42_SOURCE_HASH_MISMATCH")
    structural_audit = json.loads(
        (package / "outputs" / "phase4_structural_v1" / "ATTEMPT_AUDIT.json").read_text(encoding="utf-8")
    )
    if (
        structural_audit.get("status") != "PHASE4_2_STRUCTURAL_READY"
        or structural_audit.get("result_hash_sha256") != PHASE42_RESULT_SHA256
    ):
        raise Phase4TrainError("PHASE42_RESULT_IDENTITY_MISMATCH")
    if verify_git:
        if _git("rev-parse", "HEAD") != PHASE42_COMMIT:
            raise Phase4TrainError("PHASE42_COMMIT_MISMATCH")
        if not _git_is_clean_tracked():
            raise Phase4TrainError("TRACKED_WORKTREE_NOT_CLEAN")
    output_dir = package / OUTPUT_DIRECTORY
    registry_path = package / "registry" / "TRAIN_ATTEMPT_REGISTRY.csv"
    if check_attempt and (output_dir.exists() or _attempt_registered(registry_path)):
        raise Phase4TrainError("ATTEMPT_ALREADY_EXISTS")
    return registration


def claim_attempt(output_dir: Path) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise Phase4TrainError("ATTEMPT_ALREADY_EXISTS") from exc


def _registry_frame(registry_path: Path) -> pd.DataFrame:
    columns = [
        "attempt_id",
        "runner_version",
        "phase42_commit",
        "rule_hash_sha256",
        "engine_hash_sha256",
        "runner_source_sha256",
        "data_sha256",
        "started_at_utc",
        "completed_at_utc",
        "revealed_information_boundary",
        "research_status",
        "failure_reason",
        "status",
    ]
    if not registry_path.is_file():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(registry_path, dtype=str, keep_default_na=False)
    if list(frame.columns) != columns:
        raise Phase4TrainError("TRAIN_ATTEMPT_REGISTRY_SCHEMA_MISMATCH")
    return frame


def _update_registry(registry_path: Path, payload: dict[str, Any]) -> None:
    frame = _registry_frame(registry_path)
    row = {column: str(payload.get(column, "")) for column in frame.columns}
    if (frame["attempt_id"] == ATTEMPT_ID).any():
        frame.loc[frame["attempt_id"] == ATTEMPT_ID, :] = [row[column] for column in frame.columns]
    else:
        frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    _atomic_csv(registry_path, frame)


def _profit_factor(values: pd.Series) -> float:
    positives = float(values.loc[values > 0].sum())
    negatives = float(-values.loc[values < 0].sum())
    return positives / negatives if negatives > 0 else float("nan")


def _max_drawdown(values: pd.Series) -> float:
    cumulative = np.concatenate(([0.0], values.to_numpy(dtype=float).cumsum()))
    drawdowns = np.maximum.accumulate(cumulative) - cumulative
    return float(drawdowns.max())


def _trade_id(replay: ReplayResult) -> str:
    identity = "|".join(
        [replay.hypothesis_id, replay.session_date, str(replay.signal_time_et), str(replay.direction)]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _scan_row(scan: ScanResult, replay: ReplayResult) -> dict[str, Any]:
    signal = scan.signal
    return {
        "hypothesis_id": scan.hypothesis_id,
        "session_date": scan.session_date,
        "scan_status": scan.status,
        "signal_present": signal is not None,
        "signal_time_et": signal.signal_time_et if signal else None,
        "signal_bar_in_session": signal.bar_in_session if signal else None,
        "signal_global_pos": signal.global_pos if signal else None,
        "direction": signal.direction if signal else None,
        "evaluated_position_count": len(scan.evaluated_positions),
        "replay_status": replay.status,
        "cancellation_reason": replay.cancellation_reason,
        "entry_price": replay.entry_price,
        "stop_price": replay.stop_price,
        "target_price": replay.target_price,
        "exit_reason_stop_first": replay.exit_reason_stop_first,
        "exit_reason_target_first": replay.exit_reason_target_first,
        "same_bar_dual_trigger": (
            replay.exit_reason_stop_first == "STOP_SAME_BAR"
            and replay.exit_reason_target_first == "TARGET_SAME_BAR"
        ),
    }


def _trade_row(replay: ReplayResult) -> dict[str, Any]:
    if replay.status != "TRADE_COMPLETED" or replay.gross_return_stop_first is None:
        raise Phase4TrainError("NON_COMPLETED_REPLAY_IN_TRADE_LOG")
    gross_stop = float(replay.gross_return_stop_first)
    gross_target = float(replay.gross_return_target_first)
    return {
        "trade_id": _trade_id(replay),
        "hypothesis_id": replay.hypothesis_id,
        "session_date": replay.session_date,
        "signal_time_et": replay.signal_time_et,
        "direction": replay.direction,
        "direction_label": "LONG" if replay.direction == 1 else "SHORT",
        "entry_price": replay.entry_price,
        "stop_price": replay.stop_price,
        "target_price": replay.target_price,
        "exit_reason_stop_first": replay.exit_reason_stop_first,
        "exit_price_stop_first": replay.exit_price_stop_first,
        "exit_reason_target_first": replay.exit_reason_target_first,
        "exit_price_target_first": replay.exit_price_target_first,
        "gross_return_stop_first": gross_stop,
        "net_return_2bp_stop_first": gross_stop - SENSITIVITY_COST,
        "net_return_4bp_stop_first": gross_stop - PRIMARY_COST,
        "net_return_6bp_stop_first": gross_stop - ROBUSTNESS_COST,
        "gross_return_target_first": gross_target,
        "net_return_2bp_target_first": gross_target - SENSITIVITY_COST,
        "net_return_4bp_target_first": gross_target - PRIMARY_COST,
        "net_return_6bp_target_first": gross_target - ROBUSTNESS_COST,
        "same_bar_dual_trigger": (
            replay.exit_reason_stop_first == "STOP_SAME_BAR"
            and replay.exit_reason_target_first == "TARGET_SAME_BAR"
        ),
    }


def execute_research(
    data: QualifiedData,
    *,
    expected_days: int = TRAIN_SESSIONS,
    reveal_hook: Callable[[str], None] | None = None,
) -> ResearchBundle:
    calendar = [spec.session_date for spec in data.schedule]
    if len(calendar) != expected_days:
        raise Phase4TrainError("EXECUTION_CALENDAR_MISMATCH")
    scans: list[ScanResult] = []
    signals: list[Signal] = []
    for session_date in calendar:
        daily = scan_all(data, session_date)
        if tuple(daily) != FAMILY:
            raise Phase4TrainError("INCOMPLETE_PRIMARY_FAMILY")
        scans.extend(daily.values())
        signals.extend(result.signal for result in daily.values() if result.signal is not None)
    overlaps = tuple(family_overlap(signals))
    if len(overlaps) != 3 or overlap_gate(overlaps) != "PASS":
        raise Phase4TrainError("OVERLAP_GATE_FAILED")
    if reveal_hook:
        reveal_hook("SIGNALS_REVEALED_NO_RETURNS")

    audit_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for scan in scans:
        replay = replay_scan(data, scan)
        audit_rows.append(_scan_row(scan, replay))
        if replay.status == "TRADE_COMPLETED":
            trade_rows.append(_trade_row(replay))
    if reveal_hook:
        reveal_hook("TRAIN_RETURNS_REVEALED")
    signal_audit = pd.DataFrame(audit_rows)
    trade_log = pd.DataFrame(trade_rows, columns=TRADE_COLUMNS)
    required_trade_columns = [
        "hypothesis_id",
        "session_date",
        "gross_return_stop_first",
    ]
    if trade_log.empty:
        trades_for_statistics = pd.DataFrame(columns=["hypothesis_id", "session_date", "gross_return"])
    else:
        trades_for_statistics = trade_log.loc[:, required_trade_columns].rename(
            columns={"gross_return_stop_first": "gross_return"}
        )
    statistics = evaluate_family(trades_for_statistics, calendar, expected_days=expected_days)
    return ResearchBundle(signal_audit, trade_log, overlaps, statistics)


def _direction_metrics(trades: pd.DataFrame, direction: int) -> dict[str, Any]:
    selected = trades.loc[trades["direction"] == direction]
    net = selected["net_return_4bp_stop_first"] if not selected.empty else pd.Series(dtype=float)
    winners = net.loc[net > 0]
    losers = net.loc[net < 0]
    return {
        "count": len(selected),
        "mean_net_4bp": float(net.mean()) if len(net) else float("nan"),
        "profit_factor": _profit_factor(net),
        "win_rate": float((net > 0).mean()) if len(net) else float("nan"),
        "average_win": float(winners.mean()) if len(winners) else float("nan"),
        "average_loss": float(losers.mean()) if len(losers) else float("nan"),
    }


def build_strategy_results(
    bundle: ResearchBundle, phase42_structural: dict[str, Any]
) -> pd.DataFrame:
    summary = bundle.statistics.summary.set_index("hypothesis_id")
    rows: list[dict[str, Any]] = []
    for hypothesis_id in FAMILY:
        trades = bundle.trade_log.loc[bundle.trade_log["hypothesis_id"] == hypothesis_id]
        audits = bundle.signal_audit.loc[bundle.signal_audit["hypothesis_id"] == hypothesis_id]
        signals = audits.loc[audits["signal_present"]]
        cancellations = signals.loc[signals["replay_status"] == "SIGNAL_CANCELED"]
        primary_net = trades["net_return_4bp_stop_first"] if not trades.empty else pd.Series(dtype=float)
        winners = primary_net.loc[primary_net > 0]
        losers = primary_net.loc[primary_net < 0]
        long_metrics = _direction_metrics(trades, 1)
        short_metrics = _direction_metrics(trades, -1)
        stats = summary.loc[hypothesis_id]
        frozen_capacity = phase42_structural["mechanisms"][hypothesis_id]["complete_signal_capacity"]
        sample_qualified = (
            frozen_capacity == "CAPACITY_OK"
            and int(stats["trade_count"]) >= 50
            and int(stats["trading_days"]) >= 40
        )
        candidate = bool(stats["candidate"]) and sample_qualified
        if candidate:
            research_status = "EXPLORATORY_TRAIN_CANDIDATE"
        elif frozen_capacity != "CAPACITY_OK" or not sample_qualified:
            research_status = "NO_EVIDENCE_BELOW_MINIMUM_CAPACITY"
        else:
            research_status = "RESEARCH_NO_EDGE"
        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "trade_count": len(trades),
                "independent_trading_days": int(trades["session_date"].nunique()),
                "long_trade_count": long_metrics["count"],
                "short_trade_count": short_metrics["count"],
                "signal_count": len(signals),
                "canceled_signal_count": len(cancellations),
                "cancellation_rate_of_signals": len(cancellations) / len(signals) if len(signals) else float("nan"),
                "canceled_signal_days_per_train_day": len(cancellations) / len(audits),
                "mean_net_return_2bp": stats["mean_net_return_2bp"],
                "mean_net_return_4bp": stats["mean_net_return_4bp"],
                "mean_net_return_6bp": stats["mean_net_return_6bp"],
                "mean_net_return_4bp_bps": float(stats["mean_net_return_4bp"]) * 10_000,
                "profit_factor_4bp": stats["profit_factor"],
                "win_rate_4bp": float((primary_net > 0).mean()) if len(primary_net) else float("nan"),
                "average_win_4bp": float(winners.mean()) if len(winners) else float("nan"),
                "average_loss_4bp": float(losers.mean()) if len(losers) else float("nan"),
                "max_drawdown_4bp_additive": _max_drawdown(primary_net) if len(primary_net) else float("nan"),
                "long_mean_net_4bp": long_metrics["mean_net_4bp"],
                "short_mean_net_4bp": short_metrics["mean_net_4bp"],
                "long_profit_factor_4bp": long_metrics["profit_factor"],
                "short_profit_factor_4bp": short_metrics["profit_factor"],
                "long_win_rate_4bp": long_metrics["win_rate"],
                "short_win_rate_4bp": short_metrics["win_rate"],
                "target_first_mean_net_4bp": (
                    float(trades["net_return_4bp_target_first"].mean()) if len(trades) else float("nan")
                ),
                "same_bar_dual_trigger_count": int(trades["same_bar_dual_trigger"].sum()) if len(trades) else 0,
                "p_value_raw": stats["p_value_raw"],
                "p_value_holm": stats["p_value_holm"],
                "simultaneous_ci_low": stats["simultaneous_ci_low"],
                "simultaneous_ci_high": stats["simultaneous_ci_high"],
                "positive_months": stats["positive_months"],
                "max_positive_month_share": stats["max_positive_month_share"],
                "phase42_capacity": frozen_capacity,
                "sample_qualification": "QUALIFIED" if sample_qualified else "BELOW_MINIMUM_CAPACITY",
                "candidate": candidate,
                "research_status": research_status,
            }
        )
    return pd.DataFrame(rows)


def _buy_and_hold(data: QualifiedData) -> dict[str, float]:
    entry = float(data.bars.iloc[0]["open"])
    exit_price = float(data.bars.iloc[-1]["close"])
    gross = exit_price / entry - 1.0
    return {"entry": entry, "exit": exit_price, "gross_return": gross, "net_return_4bp": gross - PRIMARY_COST}


def build_robustness(bundle: ResearchBundle, benchmark: dict[str, float]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    paths = (("STOP_FIRST", "gross_return_stop_first", "PRIMARY"), ("TARGET_FIRST", "gross_return_target_first", "SENSITIVITY"))
    costs = ((2, SENSITIVITY_COST), (4, PRIMARY_COST), (6, ROBUSTNESS_COST))
    for hypothesis_id in FAMILY:
        selected = bundle.trade_log.loc[bundle.trade_log["hypothesis_id"] == hypothesis_id]
        for path, column, role in paths:
            for cost_bps, cost in costs:
                mean = float((selected[column] - cost).mean()) if len(selected) else float("nan")
                rows.append(
                    {
                        "hypothesis_id": hypothesis_id,
                        "path_assumption": path,
                        "path_role": role,
                        "cost_bps": cost_bps,
                        "trade_count": len(selected),
                        "mean_net_return": mean,
                        "mean_net_return_bps": mean * 10_000,
                    }
                )
    rows.append(
        {
            "hypothesis_id": "BUY_AND_HOLD",
            "path_assumption": "TRAIN_FIRST_OPEN_TO_LAST_CLOSE",
            "path_role": "DESCRIPTIVE_BENCHMARK",
            "cost_bps": 4,
            "trade_count": 1,
            "mean_net_return": benchmark["net_return_4bp"],
            "mean_net_return_bps": benchmark["net_return_4bp"] * 10_000,
        }
    )
    return pd.DataFrame(rows)


def build_statistics_gate(
    bundle: ResearchBundle,
    strategy_results: pd.DataFrame,
    registration: dict[str, Any],
) -> dict[str, Any]:
    checks = [
        ("registered_family_exact", tuple(strategy_results["hypothesis_id"]) == FAMILY),
        ("holm_family_size_three", bundle.statistics.holm_family_size == 3),
        ("bootstrap_iterations_frozen", BOOTSTRAP_ITERATIONS == 2_000),
        ("common_day_index_present", len(bundle.statistics.common_indices_sha256) == 64),
        ("statistics_engine_pass", bundle.statistics.gate_status == "PASS_ALLOW_ZERO_CANDIDATES"),
        ("no_unqualified_candidate", not strategy_results.loc[~strategy_results["sample_qualification"].eq("QUALIFIED"), "candidate"].any()),
        ("candidate_label_bounded", set(strategy_results["research_status"]).isdisjoint({"VALIDATED_EDGE", "OOS_PASS", "LIVE_READY"})),
        ("runner_source_hash_verified", registration["runner_source_sha256"] == runner_source_hash()),
    ]
    if not all(passed for _, passed in checks):
        raise Phase4TrainError("STATISTICS_GATE_FAILED")
    candidate_count = int(strategy_results["candidate"].sum())
    research_status = "EXPLORATORY_TRAIN_CANDIDATE_PRESENT" if candidate_count else "RESEARCH_NO_EDGE"
    return {
        "family_id": "P4_PRIMARY_V1",
        "family_size": 3,
        "hypotheses": list(FAMILY),
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "common_day_indices_sha256": bundle.statistics.common_indices_sha256,
        "candidate_count": candidate_count,
        "checks": [{"name": name, "status": "PASS" if passed else "FAIL"} for name, passed in checks],
        "DATA_GATE": "PASS",
        "PREREGISTRATION_GATE": "PASS",
        "ENGINE_GATE": "PASS",
        "STATISTICS_GATE": "PASS",
        "MULTIPLE_TESTING_GATE": "PASS",
        "REPRODUCIBILITY_GATE": "PASS",
        "RESEARCH_STATUS": research_status,
    }


def _fmt(value: Any, *, bps: bool = False) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if not math.isfinite(number):
        return "N/A"
    return f"{number * 10_000:+.4f} bp" if bps else f"{number:.6f}"


def render_report(
    data_report: dict[str, Any],
    strategy_results: pd.DataFrame,
    statistics_gate: dict[str, Any],
    benchmark: dict[str, float],
) -> str:
    sections = [
        "# C1 Phase 4.3 One-Shot TRAIN 研究报告",
        "",
        "## A. 数据与执行",
        "",
        f"- 数据：US.SPY 5分钟RTH，{data_report['train_start']}至{data_report['train_end']}，{data_report['train_sessions']}个交易日、{data_report['train_bars']}根K线。",
        f"- OHLC SHA256：`{data_report['input_hashes']['ohlc']}`；动态前复权；America/New_York bar-end。",
        "- 仅完整源文件用于身份核验；数值解析与特征、交易、收益计算均限制在TRAIN价格范围内。",
        "- 三机制按冻结状态机共同执行；下一根同日K线开盘成交；取消信号不计收益；STOP_FIRST为主口径。",
        "- 未读取Volume、RVOL、VWAP、1分钟、Validation/OOS、账户、持仓或订单数据。",
        f"- Buy and Hold描述性基准（首根开盘至末根收盘，扣4bp）：{_fmt(benchmark['net_return_4bp'], bps=True)}。",
        "- 最大回撤口径：按信号时间顺序累加每笔4bp后净收益，计算累计曲线相对历史峰值的最大回撤幅度；不是资金权重组合回撤。",
        "",
        "## B. 三项策略结果",
        "",
    ]
    for row in strategy_results.itertuples(index=False):
        sections.extend(
            [
                f"### {row.hypothesis_id}",
                "",
                f"- 交易/独立交易日：{row.trade_count}/{row.independent_trading_days}；Long/Short：{row.long_trade_count}/{row.short_trade_count}。",
                f"- 4bp后均值：{_fmt(row.mean_net_return_4bp, bps=True)}；PF：{_fmt(row.profit_factor_4bp)}；胜率：{_fmt(row.win_rate_4bp)}。",
                f"- 平均盈利/亏损：{_fmt(row.average_win_4bp, bps=True)} / {_fmt(row.average_loss_4bp, bps=True)}；最大回撤：{_fmt(row.max_drawdown_4bp_additive, bps=True)}。",
                f"- 2/4/6bp均值：{_fmt(row.mean_net_return_2bp, bps=True)} / {_fmt(row.mean_net_return_4bp, bps=True)} / {_fmt(row.mean_net_return_6bp, bps=True)}。",
                f"- Holm p值：{_fmt(row.p_value_holm)}；95%同时区间：[{_fmt(row.simultaneous_ci_low, bps=True)}, {_fmt(row.simultaneous_ci_high, bps=True)}]。",
                f"- 正收益月份：{row.positive_months}；最大单月正利润占比：{_fmt(row.max_positive_month_share)}。",
                f"- Long/Short 4bp均值：{_fmt(row.long_mean_net_4bp, bps=True)} / {_fmt(row.short_mean_net_4bp, bps=True)}。",
                f"- 信号取消：{row.canceled_signal_count}/{row.signal_count}；同柱双触发：{row.same_bar_dual_trigger_count}；TARGET_FIRST均值：{_fmt(row.target_first_mean_net_4bp, bps=True)}。",
                f"- 样本资格：{row.phase42_capacity}/{row.sample_qualification}；最终状态：`{row.research_status}`。",
                "",
            ]
        )
    sections.extend(["## C. 风险解释", ""])
    for row in strategy_results.itertuples(index=False):
        reasons: list[str] = []
        if row.phase42_capacity != "CAPACITY_OK":
            reasons.append("Phase 4.2已冻结为容量不足，因此收益外观不能支持晋级")
        if math.isfinite(float(row.mean_net_return_4bp)) and row.mean_net_return_4bp <= 0:
            reasons.append("4bp后平均收益不足以覆盖成本")
        if math.isfinite(float(row.mean_net_return_6bp)) and row.mean_net_return_6bp <= 0:
            reasons.append("6bp稳健性均值不大于零")
        if math.isfinite(float(row.max_positive_month_share)) and row.max_positive_month_share > 0.40:
            reasons.append("正利润受少数月份主导")
        if row.same_bar_dual_trigger_count:
            reasons.append("存在同柱路径歧义，TARGET_FIRST仅作敏感性披露")
        if not reasons:
            reasons.append("未满足全部预注册晋级条件或同时区间证据不足")
        sections.append(f"- {row.hypothesis_id}：{'；'.join(reasons)}。这些诊断不生成新过滤版本。")
    sections.extend(
        [
            "",
            "## D. 研究结论",
            "",
            f"- DATA_GATE：`{statistics_gate['DATA_GATE']}`",
            f"- PREREGISTRATION_GATE：`{statistics_gate['PREREGISTRATION_GATE']}`",
            f"- ENGINE_GATE：`{statistics_gate['ENGINE_GATE']}`",
            f"- STATISTICS_GATE：`{statistics_gate['STATISTICS_GATE']}`",
            f"- MULTIPLE_TESTING_GATE：`{statistics_gate['MULTIPLE_TESTING_GATE']}`",
            f"- REPRODUCIBILITY_GATE：`{statistics_gate['REPRODUCIBILITY_GATE']}`",
            f"- RESEARCH_STATUS：`{statistics_gate['RESEARCH_STATUS']}`",
            "",
            "工程Gate通过不等于交易优势得到验证。本报告只评价当前冻结TRAIN中的探索性假设，不构成Validation、OOS、Forward或实盘结论。",
        ]
    )
    return "\n".join(sections) + "\n"


def _artifact_manifest(output_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_OUTPUTS:
        path = output_dir / name
        if not path.is_file():
            raise Phase4TrainError(f"REQUIRED_OUTPUT_MISSING:{name}")
        artifacts[name] = {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
    return artifacts


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_one_shot(
    *,
    registration_path: Path | None = None,
    output_dir: Path | None = None,
    data_path: Path | None = None,
    audit_manifest_path: Path | None = None,
) -> dict[str, Any]:
    package = _package_dir()
    registration = verify_train_identity(registration_path)
    output = output_dir or package / OUTPUT_DIRECTORY
    audit_dir = _repo_root() / "factor_research" / "spy_factor_batch_v1" / "validation" / "train_ema_supplement_7514881494081894629"
    data_file = data_path or audit_dir / "opend_5m_ohlc.csv"
    manifest_file = audit_manifest_path or audit_dir / "manifest.json"
    registry_path = package / "registry" / "TRAIN_ATTEMPT_REGISTRY.csv"
    claim_attempt(output)
    started = _now()
    boundary = "NOT_STARTED"
    attempt = {
        "attempt_id": ATTEMPT_ID,
        "runner_version": RUNNER_VERSION,
        "status": "RUNNING",
        "research_status": "NOT_AVAILABLE",
        "started_at_utc": started,
        "completed_at_utc": None,
        "phase42_commit": PHASE42_COMMIT,
        "rule_hash_sha256": RULE_HASH_SHA256,
        "engine_hash_sha256": PHASE41_CODE_HASH,
        "runner_source_sha256": runner_source_hash(),
        "data_sha256": EXPECTED_DATA_SHA256,
        "revealed_information_boundary": boundary,
        "failure_reason": None,
        "real_train_run_count": 1,
        "automatic_retry_allowed": False,
        "validation_oos_accessed": False,
        "account_order_position_accessed": False,
    }

    def persist() -> None:
        _atomic_json(output / "ATTEMPT_AUDIT.json", attempt)
        _update_registry(registry_path, attempt)

    persist()
    try:
        data, data_report = qualify_authorized_train(data_file, manifest_file)
        boundary = "DATA_IDENTITY_VERIFIED_NO_RETURNS"
        attempt["revealed_information_boundary"] = boundary
        persist()

        def reveal_hook(new_boundary: str) -> None:
            nonlocal boundary
            boundary = new_boundary
            attempt["revealed_information_boundary"] = boundary
            persist()

        bundle = execute_research(data, reveal_hook=reveal_hook)
        phase42_structural = json.loads(
            (package / "outputs" / "phase4_structural_v1" / "STRUCTURAL_GATE.json").read_text(encoding="utf-8")
        )
        strategy_results = build_strategy_results(bundle, phase42_structural)
        statistics_gate = build_statistics_gate(bundle, strategy_results, registration)
        benchmark = _buy_and_hold(data)
        robustness = build_robustness(bundle, benchmark)
        synthetic = json.loads((package / "synthetic_validation.json").read_text(encoding="utf-8"))
        test_registry = pd.DataFrame(synthetic["checks"])

        _atomic_csv(output / "STRATEGY_RESULTS.csv", strategy_results)
        _atomic_csv(output / "TRADE_LOG.csv", bundle.trade_log)
        _atomic_csv(output / "SIGNAL_AUDIT.csv", bundle.signal_audit)
        _atomic_json(output / "STATISTICS_GATE.json", statistics_gate)
        _atomic_csv(output / "ROBUSTNESS_SUMMARY.csv", robustness)
        _atomic_csv(output / "TEST_REGISTRY.csv", test_registry)
        preregistration = json.loads((package / "preregistration.json").read_text(encoding="utf-8"))
        _atomic_json(output / "PRE_REGISTRATION_SNAPSHOT.json", preregistration)
        _atomic_text(output / "REPORT_CN.md", render_report(data_report, strategy_results, statistics_gate, benchmark))

        attempt.update(
            {
                "status": "PHASE4_3_TRAIN_COMPLETE",
                "research_status": statistics_gate["RESEARCH_STATUS"],
                "completed_at_utc": _now(),
                "revealed_information_boundary": "TRAIN_RESULTS_AND_STATISTICS_REVEALED",
                "candidate_count": statistics_gate["candidate_count"],
                "trade_count": int(len(bundle.trade_log)),
                "signal_count": int(bundle.signal_audit["signal_present"].sum()),
                "common_day_indices_sha256": bundle.statistics.common_indices_sha256,
            }
        )
        persist()
        manifest = {
            "attempt_id": ATTEMPT_ID,
            "runner_version": RUNNER_VERSION,
            "status": attempt["status"],
            "research_status": attempt["research_status"],
            "phase42_commit": PHASE42_COMMIT,
            "rule_hash_sha256": RULE_HASH_SHA256,
            "engine_hash_sha256": PHASE41_CODE_HASH,
            "runner_source_sha256": runner_source_hash(),
            "input_hashes": data_report["input_hashes"],
            "artifacts": _artifact_manifest(output),
        }
        _atomic_json(output / "manifest.json", manifest)
        return {
            "status": attempt["status"],
            "research_status": attempt["research_status"],
            "candidate_count": attempt["candidate_count"],
            "trade_count": attempt["trade_count"],
            "output_directory": str(output),
        }
    except Exception as exc:
        attempt.update(
            {
                "status": "FAILED_NO_RETRY",
                "research_status": "NOT_VALID",
                "completed_at_utc": _now(),
                "revealed_information_boundary": boundary,
                "failure_reason": f"{type(exc).__name__}:{exc}",
                "candidate_count": 0,
            }
        )
        persist()
        raise


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 4.3 one-shot TRAIN research runner; disabled by default.")
    parser.add_argument("--verify-ready-only", action="store_true")
    parser.add_argument("--authorize-one-shot-train")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.verify_ready_only:
        if args.authorize_one_shot_train:
            parser.error("VERIFY_AND_EXECUTE_ARE_MUTUALLY_EXCLUSIVE")
        registration = verify_train_identity()
        print(json.dumps({"status": "PHASE4_3_READY", "runner_source_sha256": registration["runner_source_sha256"]}, sort_keys=True))
        return 0
    if args.authorize_one_shot_train != AUTHORIZATION_TOKEN:
        parser.error(f"REAL_TRAIN_DISABLED; require --authorize-one-shot-train {AUTHORIZATION_TOKEN}")
    print(json.dumps(run_one_shot(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
