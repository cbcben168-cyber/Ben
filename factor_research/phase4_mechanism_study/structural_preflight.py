from __future__ import annotations

import csv
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import exchange_calendars as xcals
import pandas as pd

from .contracts import (
    ADJUSTMENT_BASIS,
    FAMILY,
    PRIMARY_COST,
    RULE_HASH_SHA256,
    TRAIN_END,
    TRAIN_SESSIONS,
    TRAIN_START,
    DataIncompleteError,
    Phase4ContractError,
    load_and_verify_preregistration,
)
from .mechanisms import Signal, scan_all
from .overlap import family_overlap, overlap_gate
from .run_phase4 import engine_code_hash
from .volatility import QualifiedData, qualify_ohlc

PREFLIGHT_VERSION = "PHASE4_STRUCTURAL_PREFLIGHT_V1"
ATTEMPT_ID = "P4_STRUCTURAL_V1_ONE_SHOT"
PHASE41_COMMIT = "5651e8c1ff77344126a801b7bc1092b56360d529"
PHASE41_CODE_HASH = "17b245e8d2ea070021c2bf69e4bf14eb1d499dc4bd10b59028bff4d0a00f8837"
EXPECTED_DATA_SHA256 = "e5e3ab7cfa981be022388b7a54952a6f8fa29e2dc0043672edf4e84997940e2f"
EXPECTED_REHAB_SHA256 = "16a1bae16d562edffac364cbba2a6a26d72765e1eca57ab0c31189b37ceb17c4"
EXPECTED_AUDIT_MANIFEST_SHA256 = "f1f750867dd4a32eaf74d4d776dcf47002f0aa7f5b123db4177e57c4a1a266da"
EXPECTED_TRAIN_BARS = 14_514
EARLY_CLOSES = ("2025-11-28", "2025-12-24")
OUTPUT_NAMES = (
    "DATA_QUALIFICATION.json",
    "STRUCTURAL_GATE.json",
    "OVERLAP_GATE.json",
    "ATTEMPT_AUDIT.json",
    "REPORT_CN.md",
)


class StructuralPreflightError(Phase4ContractError):
    """Fail-closed structural preflight error."""


@dataclass(frozen=True)
class EntryAssessment:
    eligible: bool
    reason: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_hash() -> str:
    return _sha256_file(Path(__file__).resolve())


def verify_preflight_identity(registration_path: Path | None = None, *, verify_git: bool = True) -> dict[str, Any]:
    base = Path(__file__).resolve().parent
    registration_file = registration_path or base / "preflight_registration.json"
    registration = json.loads(registration_file.read_text(encoding="utf-8"))
    if registration.get("preflight_version") != PREFLIGHT_VERSION or registration.get("attempt_id") != ATTEMPT_ID:
        raise StructuralPreflightError("PREFLIGHT_REGISTRATION_IDENTITY_MISMATCH")
    if registration.get("phase41_rule_hash_sha256") != RULE_HASH_SHA256:
        raise StructuralPreflightError("PHASE41_RULE_HASH_MISMATCH")
    if registration.get("phase41_code_hash_sha256") != PHASE41_CODE_HASH or engine_code_hash() != PHASE41_CODE_HASH:
        raise StructuralPreflightError("PHASE41_CODE_HASH_MISMATCH")
    load_and_verify_preregistration()
    if registration.get("preflight_source_sha256") != _source_hash():
        raise StructuralPreflightError("PREFLIGHT_SOURCE_HASH_MISMATCH")
    if verify_git:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_repo_root(), check=True, capture_output=True, text=True
        ).stdout.strip()
        if head != PHASE41_COMMIT or registration.get("phase41_commit") != head:
            raise StructuralPreflightError("PHASE41_COMMIT_MISMATCH")
    return registration


def claim_attempt(output_dir: Path) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise StructuralPreflightError("ATTEMPT_ALREADY_EXISTS") from exc


def _xnys_schedule() -> list[Any]:
    calendar = xcals.get_calendar("XNYS")
    sessions = calendar.sessions_in_range(TRAIN_START, TRAIN_END)
    if len(sessions) != TRAIN_SESSIONS:
        raise StructuralPreflightError("XNYS_SESSION_COUNT_MISMATCH")
    from .contracts import SessionSpec

    specs = []
    observed_early = []
    for session in sessions:
        session_date = session.strftime("%Y-%m-%d")
        close_time = calendar.session_close(session).tz_convert("America/New_York").strftime("%H:%M")
        if close_time == "13:00":
            observed_early.append(session_date)
        elif close_time != "16:00":
            raise StructuralPreflightError("UNEXPECTED_XNYS_CLOSE")
        specs.append(SessionSpec(session_date, close_time))
    if tuple(observed_early) != EARLY_CLOSES:
        raise StructuralPreflightError("XNYS_EARLY_CLOSE_MISMATCH")
    return specs


def _read_train_only(data_path: Path) -> pd.DataFrame:
    rows: list[list[str]] = []
    with data_path.open("r", encoding="utf-8", newline="") as handle:
        header_line = handle.readline()
        header = next(csv.reader([header_line]))
        if header != ["time_key", "open", "high", "low", "close"]:
            raise StructuralPreflightError("OHLC_SCHEMA_MISMATCH")
        for raw_line in handle:
            first_field = raw_line.split(",", 1)[0].strip('"')
            session_date = first_field[:10]
            if TRAIN_START <= session_date <= TRAIN_END:
                parsed = next(csv.reader([raw_line]))
                if len(parsed) != 5:
                    raise StructuralPreflightError("OHLC_ROW_SHAPE_MISMATCH")
                rows.append(parsed)
    if len(rows) != EXPECTED_TRAIN_BARS:
        raise DataIncompleteError("DATA_INCOMPLETE: TRAIN_BAR_COUNT")
    frame = pd.DataFrame(rows, columns=["time_key", "open", "high", "low", "close"])
    frame["time_key"] = pd.to_datetime(frame["time_key"], errors="raise")
    for column in ("open", "high", "low", "close"):
        frame[column] = pd.to_numeric(frame[column], errors="raise")
    frame["session_date"] = frame["time_key"].dt.strftime("%Y-%m-%d")
    frame["time_et"] = frame["time_key"].dt.strftime("%H:%M")
    frame["adjustment_basis"] = ADJUSTMENT_BASIS
    return frame[["session_date", "time_et", "open", "high", "low", "close", "adjustment_basis"]]


def qualify_authorized_train(data_path: Path, manifest_path: Path) -> tuple[QualifiedData, dict[str, Any]]:
    rehab_path = manifest_path.with_name("opend_rehab.csv")
    for path in (data_path, manifest_path, rehab_path):
        if not path.is_file():
            raise StructuralPreflightError(f"REQUIRED_INPUT_MISSING:{path.name}")
    hashes = {
        "ohlc": _sha256_file(data_path),
        "audit_manifest": _sha256_file(manifest_path),
        "rehab": _sha256_file(rehab_path),
    }
    expected = {
        "ohlc": EXPECTED_DATA_SHA256,
        "audit_manifest": EXPECTED_AUDIT_MANIFEST_SHA256,
        "rehab": EXPECTED_REHAB_SHA256,
    }
    if hashes != expected:
        raise StructuralPreflightError("FROZEN_DATA_HASH_MISMATCH")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    contract = manifest.get("query_contract", {})
    required_contract = {
        "adjustment": ADJUSTMENT_BASIS,
        "bar_type": "K_5M",
        "extended_time": False,
        "historical_autype": "NONE",
        "session": "RTH",
        "symbol": "US.SPY",
        "time_label": "America/New_York bar end",
    }
    if any(contract.get(key) != value for key, value in required_contract.items()):
        raise StructuralPreflightError("AUDIT_CONTRACT_MISMATCH")
    declared = manifest.get("artifacts", {})
    if declared.get("opend_5m_ohlc.csv", {}).get("sha256") != hashes["ohlc"]:
        raise StructuralPreflightError("OHLC_MANIFEST_HASH_MISMATCH")
    if declared.get("opend_rehab.csv", {}).get("sha256") != hashes["rehab"]:
        raise StructuralPreflightError("REHAB_MANIFEST_HASH_MISMATCH")
    schedule = _xnys_schedule()
    frame = _read_train_only(data_path)
    qualified = qualify_ohlc(frame, schedule, expected_session_count=TRAIN_SESSIONS)
    if len(qualified.bars) != EXPECTED_TRAIN_BARS:
        raise DataIncompleteError("DATA_INCOMPLETE: TRAIN_BAR_COUNT")
    report = {
        "status": "DATA_GATE_PASS",
        "symbol": "US.SPY",
        "timezone": "America/New_York",
        "bar_label": "bar_end",
        "bar_size": "5m",
        "adjustment_basis": ADJUSTMENT_BASIS,
        "train_start": TRAIN_START,
        "train_end": TRAIN_END,
        "train_sessions": TRAIN_SESSIONS,
        "train_bars": EXPECTED_TRAIN_BARS,
        "early_closes": list(EARLY_CLOSES),
        "input_hashes": hashes,
        "train_only_numeric_parse": True,
        "validation_oos_accessed": False,
    }
    return qualified, report


def assess_entry(data: QualifiedData, signal: Signal) -> EntryAssessment:
    day = data.session(signal.session_date).reset_index(drop=True)
    entry_position = signal.bar_in_session + 1
    if entry_position >= len(day):
        raise DataIncompleteError("DATA_INCOMPLETE: NEXT_OPEN")
    row = day.iloc[entry_position]
    if int(row["global_pos"]) != signal.global_pos + 1:
        raise DataIncompleteError("DATA_INCOMPLETE: NEXT_OPEN")
    entry = float(row["open"])
    direction = signal.direction
    stop = float(signal.stop_price)
    if direction not in (-1, 1) or direction * (entry - stop) <= 0:
        return EntryAssessment(False, "INVALID_STOP_GEOMETRY")
    if signal.target_kind == "FIXED_PRICE":
        target = float(signal.target_value)
    elif signal.target_kind == "ENTRY_R_MULTIPLE":
        initial_r = direction * (entry - stop)
        target = entry + direction * float(signal.target_value) * initial_r
    else:
        raise StructuralPreflightError("UNKNOWN_TARGET_KIND")
    target_distance = direction * (target - entry)
    if target_distance <= 0:
        reason = "GAP_TARGET_ALREADY_CROSSED" if signal.hypothesis_id == "P4_M06_ALL" else "INVALID_TARGET_GEOMETRY"
        return EntryAssessment(False, reason)
    if target_distance / entry <= PRIMARY_COST + 1e-12:
        return EntryAssessment(False, "NON_POSITIVE_NET_TARGET")
    return EntryAssessment(True, "ENTRY_ELIGIBLE")


def _capacity(event_count: int, day_count: int) -> str:
    if event_count == 0:
        return "ZERO_EVENT"
    if event_count < 50 or day_count < 40:
        return "BELOW_MINIMUM_CAPACITY"
    return "CAPACITY_OK"


def build_structural_evidence(data: QualifiedData) -> tuple[dict[str, Any], dict[str, Any], str]:
    complete: dict[str, list[Signal]] = {name: [] for name in FAMILY}
    eligible: dict[str, list[Signal]] = {name: [] for name in FAMILY}
    warmup_seen: dict[str, bool] = {name: False for name in FAMILY}
    sessions = [spec.session_date for spec in data.schedule]
    for session_date in sessions:
        scans = scan_all(data, session_date)
        if tuple(scans) != FAMILY:
            raise StructuralPreflightError("INCOMPLETE_PRIMARY_FAMILY")
        for hypothesis_id in FAMILY:
            scan = scans[hypothesis_id]
            if scan.status == "WARMUP_UNAVAILABLE":
                warmup_seen[hypothesis_id] = True
            if scan.signal is None:
                continue
            complete[hypothesis_id].append(scan.signal)
            if assess_entry(data, scan.signal).eligible:
                eligible[hypothesis_id].append(scan.signal)

    mechanisms: dict[str, Any] = {}
    for hypothesis_id in FAMILY:
        complete_days = {signal.session_date for signal in complete[hypothesis_id]}
        eligible_days = {signal.session_date for signal in eligible[hypothesis_id]}
        mechanisms[hypothesis_id] = {
            "complete_signal_capacity": _capacity(len(complete[hypothesis_id]), len(complete_days)),
            "entry_eligible_capacity": _capacity(len(eligible[hypothesis_id]), len(eligible_days)),
            "independent_signal_day_capacity": _capacity(len(eligible_days), len(eligible_days)),
            "warmup_status": "WARMUP_UNAVAILABLE_PRESENT" if warmup_seen[hypothesis_id] else "WARMUP_COMPLETE_ALL_SESSIONS",
            "daily_entitlement": "FIRST_COMPLETE_SIGNAL_CONSUMES_DAY",
        }
    structural = {
        "status": "STRUCTURAL_GATE_PASS",
        "family_id": "P4_PRIMARY_V1",
        "family_size": 3,
        "mechanisms": mechanisms,
        "counts_disclosed": False,
        "exit_replay_called": False,
        "performance_statistics_called": False,
    }

    overlaps = family_overlap(signal for values in complete.values() for signal in values)
    overlap_rows = [
        {
            "hypothesis_a": result.hypothesis_a,
            "hypothesis_b": result.hypothesis_b,
            "category": (
                "BLOCKED_HIGH_OVERLAP"
                if result.status == "HIGH_OVERLAP"
                else "OVERLAP_NOT_COMPUTABLE"
                if result.status == "OVERLAP_NOT_COMPUTABLE"
                else "PASS_BELOW_0_80"
            ),
        }
        for result in overlaps
    ]
    overlap_status = overlap_gate(overlaps)
    overlap_report = {
        "status": overlap_status,
        "matching": "SAME_SESSION_SAME_DIRECTION_BAR_DISTANCE_LE_1_ONE_TO_ONE",
        "threshold": "JACCARD_GE_0_80_BLOCKS",
        "pairs": overlap_rows,
        "exact_jaccard_disclosed": False,
    }
    overall = "PHASE4_2_BLOCKED" if overlap_status != "PASS" else "PHASE4_2_STRUCTURAL_READY"
    return structural, overlap_report, overall


def _render_report(data_report: dict[str, Any], structural: dict[str, Any], overlap: dict[str, Any], overall: str) -> str:
    lines = [
        "# Phase 4.2 结构预检报告",
        "",
        f"- 数据Gate：`{data_report['status']}`",
        f"- TRAIN身份：`{data_report['train_sessions']} sessions / {data_report['train_bars']} bars`",
        "- 收益、PF、退出路径与方向盈利排名：未计算",
        "",
        "## 结构容量类别",
        "",
    ]
    for hypothesis_id in FAMILY:
        item = structural["mechanisms"][hypothesis_id]
        lines.append(
            f"- `{hypothesis_id}`：完整信号 `{item['complete_signal_capacity']}`；"
            f"入场资格 `{item['entry_eligible_capacity']}`；独立交易日 `{item['independent_signal_day_capacity']}`。"
        )
    lines.extend(["", "## 重叠类别", ""])
    for item in overlap["pairs"]:
        lines.append(f"- `{item['hypothesis_a']}` vs `{item['hypothesis_b']}`：`{item['category']}`")
    lines.extend(["", f"`{overall}`", ""])
    return "\n".join(lines)


def _update_attempt_registry(
    registry_path: Path,
    *,
    status: str,
    started_at: str,
    completed_at: str = "",
    result_hash: str = "",
    failure_reason: str = "",
) -> None:
    fieldnames = [
        "attempt_id", "preflight_version", "phase41_commit", "rule_hash_sha256",
        "phase41_code_hash_sha256", "preflight_source_sha256", "data_sha256",
        "started_at_utc", "completed_at_utc", "result_hash_sha256", "failure_reason", "status",
    ]
    row = {
        "attempt_id": ATTEMPT_ID,
        "preflight_version": PREFLIGHT_VERSION,
        "phase41_commit": PHASE41_COMMIT,
        "rule_hash_sha256": RULE_HASH_SHA256,
        "phase41_code_hash_sha256": PHASE41_CODE_HASH,
        "preflight_source_sha256": _source_hash(),
        "data_sha256": EXPECTED_DATA_SHA256,
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "result_hash_sha256": result_hash,
        "failure_reason": failure_reason,
        "status": status,
    }
    temporary = registry_path.with_name(registry_path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    os.replace(temporary, registry_path)


def run_one_shot(
    *,
    output_dir: Path | None = None,
    data_path: Path | None = None,
    manifest_path: Path | None = None,
    registration_path: Path | None = None,
    registry_path: Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> str:
    root = _repo_root()
    package = Path(__file__).resolve().parent
    audit_dir = root / "factor_research" / "spy_factor_batch_v1" / "validation" / "train_ema_supplement_7514881494081894629"
    output = output_dir or package / "outputs" / "phase4_structural_v1"
    data_file = data_path or audit_dir / "opend_5m_ohlc.csv"
    manifest_file = manifest_path or audit_dir / "manifest.json"
    registry = registry_path or package / "registry" / "PREFLIGHT_ATTEMPT_REGISTRY.csv"
    clock = now or (lambda: datetime.now(timezone.utc))
    verify_preflight_identity(registration_path)
    claim_attempt(output)
    started = clock().isoformat()
    attempt = {
        "attempt_id": ATTEMPT_ID,
        "preflight_version": PREFLIGHT_VERSION,
        "status": "STRUCTURAL_PREFLIGHT_STARTED",
        "started_at_utc": started,
        "phase41_commit": PHASE41_COMMIT,
        "rule_hash_sha256": RULE_HASH_SHA256,
        "phase41_code_hash_sha256": PHASE41_CODE_HASH,
        "preflight_source_sha256": _source_hash(),
        "data_sha256": EXPECTED_DATA_SHA256,
        "results_revealed_before_start": False,
    }
    _atomic_json(output / "ATTEMPT_AUDIT.json", attempt)
    _update_attempt_registry(registry, status="STRUCTURAL_PREFLIGHT_STARTED", started_at=started)
    try:
        qualified, data_report = qualify_authorized_train(data_file, manifest_file)
        structural, overlap, overall = build_structural_evidence(qualified)
        completed = clock().isoformat()
        result_identity = _canonical_hash({"data": data_report, "structural": structural, "overlap": overlap, "overall": overall})
        attempt.update(
            {
                "status": overall,
                "completed_at_utc": completed,
                "result_hash_sha256": result_identity,
                "real_structural_run_count": 1,
                "performance_results_computed": False,
            }
        )
        _atomic_json(output / "DATA_QUALIFICATION.json", data_report)
        _atomic_json(output / "STRUCTURAL_GATE.json", structural)
        _atomic_json(output / "OVERLAP_GATE.json", overlap)
        _atomic_json(output / "ATTEMPT_AUDIT.json", attempt)
        _atomic_text(output / "REPORT_CN.md", _render_report(data_report, structural, overlap, overall))
        manifest = {
            "attempt_id": ATTEMPT_ID,
            "preflight_version": PREFLIGHT_VERSION,
            "status": overall,
            "result_hash_sha256": result_identity,
            "artifacts": {
                name: {"sha256": _sha256_file(output / name), "bytes": (output / name).stat().st_size}
                for name in OUTPUT_NAMES
            },
        }
        _atomic_json(output / "MANIFEST.json", manifest)
        _update_attempt_registry(
            registry,
            status=overall,
            started_at=started,
            completed_at=completed,
            result_hash=result_identity,
        )
        return overall
    except Exception as exc:
        completed = clock().isoformat()
        reason = type(exc).__name__
        attempt.update({"status": "PHASE4_2_BLOCKED", "completed_at_utc": completed, "failure_reason": reason})
        _atomic_json(output / "ATTEMPT_AUDIT.json", attempt)
        _update_attempt_registry(
            registry,
            status="PHASE4_2_BLOCKED",
            started_at=started,
            completed_at=completed,
            failure_reason=reason,
        )
        raise


def main() -> int:
    status = run_one_shot()
    print(status)
    return 0 if status == "PHASE4_2_STRUCTURAL_READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
