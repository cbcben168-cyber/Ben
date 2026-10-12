from __future__ import annotations

import json

from factor_research.phase3_edge_engine.data import sha256_file
from factor_research.phase3_edge_engine.pipeline import DEFAULT_AUDIT_MANIFEST, DEFAULT_DATA, run_pipeline


def test_pipeline_outputs_are_complete_hashed_and_deterministic(tmp_path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    manifest = run_pipeline(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST, first)
    manifest_two = run_pipeline(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST, second)
    assert manifest["state_machine_consistency"]["status"] == "PASS"
    assert manifest["registry"] == {"factor_count": 36, "strategy_variant_count": 9}
    required = {
        "RESEARCH_PLAN.md", "DATA_QUALIFICATION.md", "FACTOR_REGISTRY.csv",
        "STRATEGY_REGISTRY.csv", "FACTOR_CORRELATION.csv", "FACTOR_RESULTS.csv",
        "STRATEGY_RESULTS.csv", "REGIME_TIME_MATRIX.csv", "ROBUSTNESS_SUMMARY.csv",
        "TEST_REGISTRY.csv", "CANDIDATE_SHORTLIST.csv", "REPORT_CN.md",
        "TRADE_LOG.csv", "SIGNAL_REPLAY_AUDIT.csv", "V3_1_1_CONSISTENCY.json",
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


def test_shortlist_is_allowed_to_be_empty(phase3_state, tmp_path):
    output = tmp_path / "none"
    manifest = run_pipeline(DEFAULT_DATA, DEFAULT_AUDIT_MANIFEST, output)
    shortlist = (output / "CANDIDATE_SHORTLIST.csv").read_text(encoding="utf-8")
    assert len(shortlist.splitlines()) == 1
    assert manifest["validation_oos_accessed"] is False
    assert manifest["orders_accounts_positions_accessed"] is False
