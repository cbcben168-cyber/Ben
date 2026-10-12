from __future__ import annotations

import json

import pytest

from factor_research.phase4_mechanism_study.contracts import (
    FAMILY,
    RULE_HASH_SHA256,
    Phase4ContractError,
    assert_as_of_positions,
    assert_strict_past_window,
    load_and_verify_preregistration,
)
from factor_research.phase4_mechanism_study.run_phase4 import engine_code_hash, verify_frozen_contract


def test_frozen_rule_and_code_hashes_recompute_exactly() -> None:
    document = load_and_verify_preregistration()
    assert document["rule_hash_sha256"] == RULE_HASH_SHA256
    assert document["code_hash_sha256"] == engine_code_hash()
    assert verify_frozen_contract()["status"] == "PHASE4_1_CONTRACT_VERIFIED"


def test_rule_mutation_is_rejected(tmp_path) -> None:
    source = load_and_verify_preregistration()
    source["rules"]["execution"]["primary_cost_bps"] = 0.0
    altered = tmp_path / "altered.json"
    altered.write_text(json.dumps(source), encoding="utf-8")
    with pytest.raises(Phase4ContractError, match="RULE_HASH_MISMATCH"):
        load_and_verify_preregistration(altered)


def test_current_bar_in_historical_window_and_future_access_are_rejected() -> None:
    with pytest.raises(Phase4ContractError, match="LOOKAHEAD_OR_WINDOW_LENGTH_VIOLATION"):
        assert_strict_past_window(0, 13, current=12, expected_count=12)
    with pytest.raises(Phase4ContractError, match="FUTURE_DATA_ACCESS"):
        assert_as_of_positions([0, 1, 13], current=12)


def test_primary_family_is_immutable_and_deferred_mechanisms_are_not_executable() -> None:
    document = load_and_verify_preregistration()
    family = document["rules"]["family"]
    assert tuple(family["hypotheses"]) == FAMILY
    assert family["size"] == 3
    assert family["deferred"] == ["P4_M03", "P4_M04", "P4_M05"]
