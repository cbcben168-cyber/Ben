"""Contract tests for V2.1 provisional evidence and formal eligibility."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import hashlib
import inspect
import json
from pathlib import Path

import pytest

import tv_quant.contracts.artifact_contract as artifact_contract
from tv_quant.contracts.artifact_contract import (
    ARTIFACT_OWNERS,
    ArtifactContract,
    DependencyFingerprint,
    FormalResultContract,
    ProvisionalEvidence,
    dependency_hash,
    formal_eligibility,
)
import tv_quant.run_manifest as run_manifest
from tv_quant.run_manifest import bind_artifact_hashes, write_canonical_json_artifact


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _fingerprint() -> DependencyFingerprint:
    return DependencyFingerprint(
        schema_version="v2.1",
        validator_version="validator-1",
        normalizer_version="normalizer-1",
        compiler_version="compiler-1",
        capability_snapshot_hash=SHA_A,
        status_registry_hash=SHA_B,
        cost_profile_id="phase1-costs",
        cost_profile_hash=SHA_C,
        corporate_action_profile_id="phase1-corporate-actions",
        corporate_action_profile_hash=SHA_D,
        benchmark_protocol_version="benchmark-1",
        engine_id="NOT_IMPLEMENTED",
        engine_version="NOT_IMPLEMENTED",
        data_contract_version="daily-ohlcv-1",
        plugin_name=None,
        plugin_version=None,
        plugin_hash=None,
    )


def _evidence(**changes: object) -> ProvisionalEvidence:
    evidence = ProvisionalEvidence(
        run_id="run-13",
        evidence_kind="validation",
        paths=("validation.json",),
        config_hash=SHA_A,
        data_plan_hash=SHA_B,
        capability_snapshot_hash=SHA_C,
        status="NOT_IMPLEMENTED",
        formal_result_published=False,
    )
    return replace(evidence, **changes)


def test_existing_run_manifest_hash_owner_is_declared() -> None:
    declared = {
        (owner.artifact_kind, owner.owner_module, owner.owner_function, owner.required)
        for owner in ARTIFACT_OWNERS
    }

    assert {
        ("canonical_hash", "tv_quant.run_manifest", "canonical_hash", True),
        ("file_hash", "tv_quant.run_manifest", "sha256_file", True),
        ("bytes_hash", "tv_quant.run_manifest", "sha256_bytes", True),
        ("artifact_hash_binding", "tv_quant.run_manifest", "bind_artifact_hashes", True),
        (
            "data_provenance",
            "tv_quant.research_pipeline",
            "write_data_provenance",
            True,
        ),
        ("backtest_audit", "tv_quant.backtest_audit", "audit_backtest", True),
        ("formal_report", "tv_quant.reporting", "write_reports", True),
    }.issubset(declared)


def test_dependency_hash_payload_contains_all_components() -> None:
    payload = {
        "schema_version": "v2.1",
        "validator_version": "validator-1",
        "normalizer_version": "normalizer-1",
        "compiler_version": "compiler-1",
        "capability_snapshot_hash": SHA_A,
        "status_registry_hash": SHA_B,
        "cost_profile_id": "phase1-costs",
        "cost_profile_hash": SHA_C,
        "corporate_action_profile_id": "phase1-corporate-actions",
        "corporate_action_profile_hash": SHA_D,
        "benchmark_protocol_version": "benchmark-1",
        "engine_id": "NOT_IMPLEMENTED",
        "engine_version": "NOT_IMPLEMENTED",
        "data_contract_version": "daily-ohlcv-1",
        "plugin_name": None,
        "plugin_version": None,
        "plugin_hash": None,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")

    assert dependency_hash(_fingerprint()) == hashlib.sha256(serialized).hexdigest()


def test_provisional_evidence_accepts_only_contained_paths(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    nested.mkdir()
    evidence = _evidence(paths=("validation.json", "nested/config.json"))

    assert evidence.resolved_paths(tmp_path) == (
        tmp_path / "validation.json",
        nested / "config.json",
    )

    for unsafe in ("../escape.json", "/absolute.json", r"C:\escape.json", r"\\host\share\x"):
        with pytest.raises(ValueError):
            _evidence(paths=(unsafe,))


def test_formal_result_requires_all_five_conditions_and_dependency_hash() -> None:
    eligible = FormalResultContract(
        execution_complete=True,
        final_audit_acceptable=True,
        artifact_hashes_complete=True,
        blocking_status_absent=True,
        atomic_publish_complete=True,
        dependency_hash=dependency_hash(_fingerprint()),
    )

    assert formal_eligibility(eligible) is True
    for field_name in (
        "execution_complete",
        "final_audit_acceptable",
        "artifact_hashes_complete",
        "blocking_status_absent",
        "atomic_publish_complete",
    ):
        assert formal_eligibility(replace(eligible, **{field_name: False})) is False
    assert formal_eligibility(replace(eligible, dependency_hash="")) is False
    assert formal_eligibility(replace(eligible, dependency_hash="A" * 64)) is False


def test_v21_execute_cannot_mark_formal_result_published() -> None:
    assert _evidence().formal_result_published is False

    with pytest.raises(ValueError):
        _evidence(formal_result_published=True)


def test_provisional_evidence_rejects_drive_relative_and_ads_run_ids() -> None:
    for unsafe_run_id in ("C:run", "run:stream"):
        with pytest.raises(ValueError):
            _evidence(run_id=unsafe_run_id)


def test_contract_does_not_define_second_hash_or_manifest_writer() -> None:
    assert artifact_contract.canonical_hash is run_manifest.canonical_hash
    assert artifact_contract.sha256_file is run_manifest.sha256_file
    assert artifact_contract.sha256_bytes is run_manifest.sha256_bytes
    assert artifact_contract.bind_artifact_hashes is run_manifest.bind_artifact_hashes
    assert not hasattr(artifact_contract, "build_manifest")
    assert not hasattr(artifact_contract, "write_manifest")

    source = inspect.getsource(artifact_contract)
    assert "import hashlib" not in source
    assert "import json" not in source
    assert ".write_text(" not in source
    assert ".write_bytes(" not in source


def test_extended_artifact_binding_preserves_legacy_default() -> None:
    assert (
        inspect.signature(bind_artifact_hashes).parameters["hashed_names"].kind.name
        == "KEYWORD_ONLY"
    )
    assert ArtifactContract().owners == ARTIFACT_OWNERS


@pytest.mark.parametrize(
    "value",
    [
        Path("x"),
        datetime(2026, 8, 2),
        {"x"},
        b"x",
        float("nan"),
        float("inf"),
        object(),
    ],
)
def test_canonical_json_rejects_non_json_values(tmp_path: Path, value: object) -> None:
    with pytest.raises(TypeError, match="canonical JSON"):
        write_canonical_json_artifact(tmp_path / "x.json", {"value": value})


def test_v22a_artifact_refs_are_relative_and_separate_from_hash_paths(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifact.json"
    path.write_text("{}", encoding="utf-8")

    bound = bind_artifact_hashes(
        {"schema_version": "v2.2a"},
        {"report": path},
        persisted_refs={"report": "reports/import-1/report.json"},
        hashed_names=("report",),
    )

    assert bound["artifact_refs"] == {"report": "reports/import-1/report.json"}
    assert "artifact_paths" not in bound and str(tmp_path) not in json.dumps(bound)
