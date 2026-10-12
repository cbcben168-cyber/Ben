from __future__ import annotations

import json
from pathlib import Path

import pytest

from factor_research.phase4_mechanism_study.lifecycle import verify_post_checkpoint_identity
from factor_research.phase4_mechanism_study.structural_preflight import (
    ATTEMPT_ID,
    PHASE41_CODE_HASH,
    PREFLIGHT_VERSION,
    StructuralPreflightError,
)


def test_post_checkpoint_identity_preserves_phase41_and_accepts_descendant_head() -> None:
    registration = verify_post_checkpoint_identity()
    assert registration["attempt_id"] == ATTEMPT_ID
    assert registration["preflight_version"] == PREFLIGHT_VERSION
    assert registration["phase41_code_hash_sha256"] == PHASE41_CODE_HASH
    assert registration["phase41_checkpoint_relation"] == "ANCESTOR_OR_EQUAL"


def test_post_checkpoint_identity_still_rejects_registered_source_tampering(tmp_path: Path) -> None:
    registration = verify_post_checkpoint_identity()
    registration["preflight_source_sha256"] = "0" * 64
    altered = tmp_path / "preflight_registration.json"
    altered.write_text(json.dumps(registration), encoding="utf-8")
    with pytest.raises(StructuralPreflightError, match="PREFLIGHT_SOURCE_HASH_MISMATCH"):
        verify_post_checkpoint_identity(altered)
