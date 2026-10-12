from __future__ import annotations

import json
from pathlib import Path

import pytest

from factor_research.phase4_mechanism_study.contracts import FAMILY
from factor_research.phase4_mechanism_study.phase432_structural_preflight import (
    ATTEMPT_ID,
    AUTHORIZATION_TOKEN,
    OUTPUT_DIRECTORY,
    PHASE431_CHECKPOINT,
    PREFLIGHT_VERSION,
    CorrectedStructuralPreflightError,
    claim_attempt,
    main,
    source_hashes,
    verify_corrected_preflight_identity,
)


def test_corrected_preflight_has_new_identity_and_binds_repair_sources() -> None:
    registration = verify_corrected_preflight_identity(verify_git=False, check_attempt=False)
    assert registration["attempt_id"] == ATTEMPT_ID
    assert registration["preflight_version"] == PREFLIGHT_VERSION
    assert registration["phase431_checkpoint"] == PHASE431_CHECKPOINT
    assert registration["output_directory"] == OUTPUT_DIRECTORY
    assert tuple(registration["hypotheses"]) == FAMILY
    assert registration["minimum_events"] == 50
    assert registration["minimum_independent_days"] == 40
    assert registration["statistical_family"] == "P4_PRIMARY_V1_HOLM_MAX_T"
    assert {key: registration[key] for key in source_hashes()} == source_hashes()
    assert "phase42_result_sha256" not in registration


def test_adapter_or_preflight_source_hash_drift_fails_closed(tmp_path: Path) -> None:
    registration = verify_corrected_preflight_identity(verify_git=False, check_attempt=False)
    for key in ("input_integrity_source_sha256", "preflight_source_sha256"):
        altered = dict(registration)
        altered[key] = "0" * 64
        path = tmp_path / f"{key}.json"
        path.write_text(json.dumps(altered), encoding="utf-8")
        with pytest.raises(CorrectedStructuralPreflightError, match="SOURCE_HASH_MISMATCH"):
            verify_corrected_preflight_identity(path, verify_git=False, check_attempt=False)


def test_new_attempt_directory_is_one_shot_and_separate_from_v1(tmp_path: Path) -> None:
    assert OUTPUT_DIRECTORY == "outputs/phase4_structural_v2"
    output = tmp_path / "phase4_structural_v2"
    claim_attempt(output)
    with pytest.raises(CorrectedStructuralPreflightError, match="ATTEMPT_ALREADY_EXISTS"):
        claim_attempt(output)


def test_cli_cannot_execute_without_exact_corrected_preflight_authorization() -> None:
    with pytest.raises(SystemExit):
        main([])
    with pytest.raises(SystemExit):
        main(["--authorize-one-shot-preflight", "WRONG"])
    assert AUTHORIZATION_TOKEN == ATTEMPT_ID


def test_production_source_uses_numeric_adapter_and_never_reads_old_capacity_result() -> None:
    source = Path(__file__).parents[1].joinpath("phase432_structural_preflight.py").read_text(
        encoding="utf-8"
    )
    assert "qualify_authorized_train_repaired" in source
    assert "phase4_structural_v1" not in source
    assert "PHASE42_RESULT" not in source
    assert "build_structural_evidence(qualified)" in source
