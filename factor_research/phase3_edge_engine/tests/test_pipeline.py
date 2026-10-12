from __future__ import annotations

import json

from factor_research.phase3_edge_engine.data import sha256_file
import pytest

from factor_research.phase3_edge_engine.pipeline import (
    DEFAULT_AUDIT_MANIFEST,
    DEFAULT_DATA,
    PHASE3_V1_OUTPUT,
    PHASE3_V2_OUTPUT,
    run_pipeline,
)


def test_pipeline_outputs_are_complete_hashed_and_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = run_pipeline(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST, first)
    manifest_two = run_pipeline(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST, second)
    assert manifest["state_machine_consistency"]["status"] == "PASS"
    assert manifest["engine_status"] == "ENGINE_PASS"
    assert manifest["statistics_status"] == "STATISTICS_PASS"
    assert manifest["statistics_gate"]["checks_failed"] == 0
    assert manifest["trade_parity"]["status"] == "TRADE_PARITY_PASS"
    assert manifest["acceptance_status"] == "ACCEPTANCE_PASS"
    assert manifest["research_status"] == "RESEARCH_NO_EDGE"
    assert manifest["registry"] == {"factor_count": 36, "strategy_variant_count": 9}
    required = {
        "RESEARCH_PLAN.md", "DATA_QUALIFICATION.md", "FACTOR_REGISTRY.csv",
        "STRATEGY_REGISTRY.csv", "FACTOR_CORRELATION.csv", "FACTOR_RESULTS.csv",
        "STRATEGY_RESULTS.csv", "REGIME_TIME_MATRIX.csv", "ROBUSTNESS_SUMMARY.csv",
        "TEST_REGISTRY.csv", "CANDIDATE_SHORTLIST.csv", "REPORT_CN.md",
        "TRADE_LOG.csv", "SIGNAL_REPLAY_AUDIT.csv", "V3_1_1_CONSISTENCY.json",
        "V3_1_1_TRADE_PARITY.csv", "V3_1_1_TRADE_PARITY.json",
        "FACTOR_RESULTS_V2_V3.csv", "STRATEGY_RESULTS_V2_V3.csv",
        "V2_V3_CHANGE_AUDIT_CN.md", "STATISTICS_GATE.json",
        "manifest.json",
    }
    assert required == {path.name for path in first.iterdir()}
    disk_manifest = json.loads((first / "manifest.json").read_text(encoding="utf-8"))
    for name, item in disk_manifest["artifacts"].items():
        assert sha256_file(first / name) == item["sha256"]
    deterministic = required - {"REPORT_CN.md", "manifest.json"}
    assert {name: sha256_file(first / name) for name in deterministic} == {
        name: sha256_file(second / name) for name in deterministic
    }
    assert manifest_two["state_machine_consistency"]["status"] == "PASS"
    assert manifest_two["trade_parity"]["status"] == "TRADE_PARITY_PASS"
    assert manifest_two["statistics_status"] == "STATISTICS_PASS"


def test_shortlist_is_allowed_to_be_empty(phase3_state, tmp_path):
    output = tmp_path / "none"
    manifest = run_pipeline(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST, output)
    shortlist = (output / "CANDIDATE_SHORTLIST.csv").read_text(encoding="utf-8")
    assert len(shortlist.splitlines()) == 1
    assert manifest["validation_oos_accessed"] is False
    assert manifest["orders_accounts_positions_accessed"] is False
    assert manifest["trade_parity"]["errors"] == []


@pytest.mark.parametrize("protected", [PHASE3_V1_OUTPUT, PHASE3_V2_OUTPUT])
def test_pipeline_refuses_frozen_output_directories(protected):
    with pytest.raises(RuntimeError, match="PROTECTED_OUTPUT_PATH"):
        run_pipeline(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST, protected)


def test_pipeline_refuses_to_overwrite_an_existing_directory(tmp_path):
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(RuntimeError, match="OUTPUT_DIRECTORY_ALREADY_EXISTS"):
        run_pipeline(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST, existing)
