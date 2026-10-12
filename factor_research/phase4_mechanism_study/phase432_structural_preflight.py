from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from .contracts import FAMILY, RULE_HASH_SHA256, load_and_verify_preregistration
from .input_integrity import qualify_authorized_train_repaired
from .run_phase4 import engine_code_hash
from .structural_preflight import (
    EXPECTED_AUDIT_MANIFEST_SHA256,
    EXPECTED_DATA_SHA256,
    EXPECTED_REHAB_SHA256,
    PHASE41_CODE_HASH,
    StructuralPreflightError,
    build_structural_evidence,
)

PREFLIGHT_VERSION = "PHASE4_3_2_CORRECTED_STRUCTURAL_PREFLIGHT_V1"
ATTEMPT_ID = "P4_3_2_CORRECTED_STRUCTURAL_V1_ONE_SHOT"
AUTHORIZATION_TOKEN = ATTEMPT_ID
PHASE431_CHECKPOINT = "a0d43e0380b78c96759e55dbddf5b77b44e4c648"
OUTPUT_DIRECTORY = "outputs/phase4_structural_v2"
REGISTRY_FILE = "registry/CORRECTED_PREFLIGHT_ATTEMPT_REGISTRY.csv"
READY_STATUS = "PHASE4_3_2_CORRECTED_STRUCTURAL_READY"
BLOCKED_STATUS = "PHASE4_3_2_BLOCKED"
REQUIRED_OUTPUTS = (
    "ATTEMPT_AUDIT.json",
    "DATA_QUALIFICATION.json",
    "STRUCTURAL_GATE.json",
    "OVERLAP_GATE.json",
    "REPORT_CN.md",
)


class CorrectedStructuralPreflightError(StructuralPreflightError):
    """A fail-closed Phase 4.3.2 corrected-preflight violation."""


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


def _source_paths() -> dict[str, Path]:
    package = _package_dir()
    return {
        "preflight_source_sha256": Path(__file__).resolve(),
        "input_integrity_source_sha256": package / "input_integrity.py",
        "lifecycle_source_sha256": package / "lifecycle.py",
        "structural_engine_source_sha256": package / "structural_preflight.py",
    }


def source_hashes() -> dict[str, str]:
    return {name: _sha256_file(path) for name, path in _source_paths().items()}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, check=False, capture_output=True, text=True)


def _attempt_registered(registry_path: Path) -> bool:
    if not registry_path.is_file():
        return False
    with registry_path.open("r", encoding="utf-8", newline="") as handle:
        return any(row.get("attempt_id") == ATTEMPT_ID for row in csv.DictReader(handle))


def verify_corrected_preflight_identity(
    registration_path: Path | None = None,
    *,
    repo_root: Path | None = None,
    verify_git: bool = True,
    check_attempt: bool = True,
) -> dict[str, Any]:
    package = _package_dir()
    registration_file = registration_path or package / "preflight_registration_v2.json"
    registration = json.loads(registration_file.read_text(encoding="utf-8"))
    expected = {
        "attempt_id": ATTEMPT_ID,
        "preflight_version": PREFLIGHT_VERSION,
        "phase431_checkpoint": PHASE431_CHECKPOINT,
        "phase41_rule_hash_sha256": RULE_HASH_SHA256,
        "phase41_code_hash_sha256": PHASE41_CODE_HASH,
        "data_sha256": EXPECTED_DATA_SHA256,
        "audit_manifest_sha256": EXPECTED_AUDIT_MANIFEST_SHA256,
        "rehab_sha256": EXPECTED_REHAB_SHA256,
        "output_directory": OUTPUT_DIRECTORY,
        "family_id": "P4_PRIMARY_V1",
        "family_size": len(FAMILY),
        "minimum_events": 50,
        "minimum_independent_days": 40,
        "real_run_limit": 1,
    }
    mismatches = [key for key, value in expected.items() if registration.get(key) != value]
    if mismatches:
        raise CorrectedStructuralPreflightError(
            "CORRECTED_PREFLIGHT_REGISTRATION_MISMATCH:" + ",".join(mismatches)
        )
    if tuple(registration.get("hypotheses", ())) != FAMILY:
        raise CorrectedStructuralPreflightError("INCOMPLETE_PRIMARY_FAMILY")
    observed_hashes = source_hashes()
    hash_mismatches = [key for key, value in observed_hashes.items() if registration.get(key) != value]
    if hash_mismatches:
        raise CorrectedStructuralPreflightError(
            "CORRECTED_PREFLIGHT_SOURCE_HASH_MISMATCH:" + ",".join(hash_mismatches)
        )
    load_and_verify_preregistration()
    if engine_code_hash() != PHASE41_CODE_HASH:
        raise CorrectedStructuralPreflightError("PHASE41_ENGINE_HASH_MISMATCH")

    root = repo_root or _repo_root()
    if verify_git:
        head = _git(root, "rev-parse", "HEAD")
        if head.returncode:
            raise CorrectedStructuralPreflightError("GIT_HEAD_UNAVAILABLE")
        ancestor = _git(root, "merge-base", "--is-ancestor", PHASE431_CHECKPOINT, head.stdout.strip())
        if ancestor.returncode:
            raise CorrectedStructuralPreflightError("PHASE431_CHECKPOINT_NOT_ANCESTOR")
        dirty = _git(root, "status", "--porcelain=v1", "--untracked-files=no")
        if dirty.returncode or dirty.stdout.strip():
            raise CorrectedStructuralPreflightError("TRACKED_WORKTREE_NOT_CLEAN")
    output = package / OUTPUT_DIRECTORY
    registry = package / REGISTRY_FILE
    if check_attempt and (output.exists() or _attempt_registered(registry)):
        raise CorrectedStructuralPreflightError("ATTEMPT_ALREADY_EXISTS")
    return {
        **registration,
        "current_head": _git(root, "rev-parse", "HEAD").stdout.strip() if verify_git else None,
        "phase431_checkpoint_relation": "ANCESTOR_OR_EQUAL" if verify_git else "NOT_CHECKED",
    }


def claim_attempt(output_dir: Path) -> None:
    try:
        output_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise CorrectedStructuralPreflightError("ATTEMPT_ALREADY_EXISTS") from exc


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _atomic_json(path: Path, payload: Any) -> None:
    _atomic_text(path, json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _canonical_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _update_registry(
    registry_path: Path,
    *,
    status: str,
    started_at: str,
    completed_at: str = "",
    result_hash: str = "",
    failure_reason: str = "",
) -> None:
    fieldnames = [
        "attempt_id",
        "preflight_version",
        "phase431_checkpoint",
        "rule_hash_sha256",
        "phase41_code_hash_sha256",
        "input_integrity_source_sha256",
        "started_at_utc",
        "completed_at_utc",
        "result_hash_sha256",
        "failure_reason",
        "status",
    ]
    row = {
        "attempt_id": ATTEMPT_ID,
        "preflight_version": PREFLIGHT_VERSION,
        "phase431_checkpoint": PHASE431_CHECKPOINT,
        "rule_hash_sha256": RULE_HASH_SHA256,
        "phase41_code_hash_sha256": PHASE41_CODE_HASH,
        "input_integrity_source_sha256": source_hashes()["input_integrity_source_sha256"],
        "started_at_utc": started_at,
        "completed_at_utc": completed_at,
        "result_hash_sha256": result_hash,
        "failure_reason": failure_reason,
        "status": status,
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = registry_path.with_name(registry_path.name + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerow(row)
    os.replace(temporary, registry_path)


def _render_report(
    data_report: dict[str, Any], structural: dict[str, Any], overlap: dict[str, Any], overall: str
) -> str:
    lines = [
        "# Phase 4.3.2 纠错结构预检报告",
        "",
        f"- 数据Gate：`{data_report['status']}`",
        f"- Phase 3数组交叉核验：`{data_report['phase3_cross_check']}`",
        f"- TRAIN身份：`{data_report['train_sessions']} sessions / {data_report['train_bars']} bars`",
        f"- Phase 4.3.1 checkpoint：`{PHASE431_CHECKPOINT}`",
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


def _artifact_manifest(output_dir: Path) -> dict[str, dict[str, Any]]:
    artifacts: dict[str, dict[str, Any]] = {}
    for name in REQUIRED_OUTPUTS:
        path = output_dir / name
        if not path.is_file():
            raise CorrectedStructuralPreflightError(f"REQUIRED_OUTPUT_MISSING:{name}")
        artifacts[name] = {"sha256": _sha256_file(path), "bytes": path.stat().st_size}
    return artifacts


def run_one_shot(
    *,
    registration_path: Path | None = None,
    output_dir: Path | None = None,
    data_path: Path | None = None,
    audit_manifest_path: Path | None = None,
    registry_path: Path | None = None,
    now: Callable[[], str] | None = None,
) -> str:
    package = _package_dir()
    registration = verify_corrected_preflight_identity(registration_path)
    output = output_dir or package / OUTPUT_DIRECTORY
    registry = registry_path or package / REGISTRY_FILE
    audit_dir = (
        _repo_root()
        / "factor_research"
        / "spy_factor_batch_v1"
        / "validation"
        / "train_ema_supplement_7514881494081894629"
    )
    data_file = data_path or audit_dir / "opend_5m_ohlc.csv"
    manifest_file = audit_manifest_path or audit_dir / "manifest.json"
    clock = now or _now
    claim_attempt(output)
    started = clock()
    attempt = {
        "attempt_id": ATTEMPT_ID,
        "preflight_version": PREFLIGHT_VERSION,
        "status": "CORRECTED_STRUCTURAL_PREFLIGHT_STARTED",
        "started_at_utc": started,
        "completed_at_utc": None,
        "phase431_checkpoint": PHASE431_CHECKPOINT,
        "source_hashes": source_hashes(),
        "data_sha256": EXPECTED_DATA_SHA256,
        "results_revealed_before_start": False,
        "performance_results_computed": False,
    }
    _atomic_json(output / "ATTEMPT_AUDIT.json", attempt)
    _update_registry(registry, status=attempt["status"], started_at=started)
    try:
        qualified, data_report = qualify_authorized_train_repaired(data_file, manifest_file)
        if (
            data_report.get("status") != "DATA_GATE_PASS_NUMERIC_ADJUSTMENT_VERIFIED"
            or data_report.get("phase3_cross_check") != "EXACT_ARRAY_MATCH"
        ):
            raise CorrectedStructuralPreflightError("NUMERIC_ADJUSTMENT_GATE_NOT_PASS")
        data_report = {
            **data_report,
            "phase431_checkpoint": PHASE431_CHECKPOINT,
            "source_hashes": source_hashes(),
        }
        structural, overlap, legacy_overall = build_structural_evidence(qualified)
        overall = BLOCKED_STATUS if legacy_overall == "PHASE4_2_BLOCKED" else READY_STATUS
        completed = clock()
        result_hash = _canonical_hash(
            {"data": data_report, "structural": structural, "overlap": overlap, "overall": overall}
        )
        attempt.update(
            {
                "status": overall,
                "completed_at_utc": completed,
                "result_hash_sha256": result_hash,
                "real_structural_run_count": 1,
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
            "phase431_checkpoint": PHASE431_CHECKPOINT,
            "source_hashes": source_hashes(),
            "registration_sha256": _sha256_file(
                registration_path or package / "preflight_registration_v2.json"
            ),
            "result_hash_sha256": result_hash,
            "artifacts": _artifact_manifest(output),
        }
        _atomic_json(output / "MANIFEST.json", manifest)
        _update_registry(
            registry,
            status=overall,
            started_at=started,
            completed_at=completed,
            result_hash=result_hash,
        )
        return overall
    except Exception as exc:
        completed = clock()
        attempt.update(
            {
                "status": BLOCKED_STATUS,
                "completed_at_utc": completed,
                "failure_reason": f"{type(exc).__name__}:{exc}",
            }
        )
        _atomic_json(output / "ATTEMPT_AUDIT.json", attempt)
        _update_registry(
            registry,
            status=BLOCKED_STATUS,
            started_at=started,
            completed_at=completed,
            failure_reason=attempt["failure_reason"],
        )
        raise


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4.3.2 corrected structural preflight; real run disabled by default."
    )
    parser.add_argument("--verify-ready-only", action="store_true")
    parser.add_argument("--authorize-one-shot-preflight")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.verify_ready_only:
        if args.authorize_one_shot_preflight:
            parser.error("VERIFY_AND_EXECUTE_ARE_MUTUALLY_EXCLUSIVE")
        registration = verify_corrected_preflight_identity()
        print(
            json.dumps(
                {
                    "status": "PHASE4_3_2_LAUNCH_READY",
                    "phase431_checkpoint": registration["phase431_checkpoint"],
                    "source_hashes": source_hashes(),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.authorize_one_shot_preflight != AUTHORIZATION_TOKEN:
        parser.error(
            "REAL_CORRECTED_PREFLIGHT_DISABLED; require "
            f"--authorize-one-shot-preflight {AUTHORIZATION_TOKEN}"
        )
    print(run_one_shot())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
