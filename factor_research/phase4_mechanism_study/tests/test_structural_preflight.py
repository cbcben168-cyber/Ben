from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import exchange_calendars
import pytest

from factor_research.phase4_mechanism_study.contracts import FAMILY, Phase4ContractError
from factor_research.phase4_mechanism_study.mechanisms import Signal
from factor_research.phase4_mechanism_study.overlap import pair_overlap
from factor_research.phase4_mechanism_study.structural_preflight import (
    ATTEMPT_ID,
    PHASE41_CODE_HASH,
    PREFLIGHT_VERSION,
    StructuralPreflightError,
    assess_entry,
    build_structural_evidence,
    claim_attempt,
    verify_preflight_identity,
)
from factor_research.phase4_mechanism_study.volatility import qualify_ohlc

from .conftest import qualified, set_bar, set_m01, synthetic_frame, synthetic_schedule


def _signal(hypothesis: str, day: str, position: int, direction: int = 1) -> Signal:
    return Signal(hypothesis, day, position, position, "10:00", direction, 99.0, "FIXED_PRICE", 101.0, 6, {})


def test_preflight_has_independent_frozen_identity_and_python314_dependencies() -> None:
    registration = verify_preflight_identity()
    assert registration["attempt_id"] == ATTEMPT_ID
    assert registration["preflight_version"] == PREFLIGHT_VERSION
    assert registration["phase41_code_hash_sha256"] == PHASE41_CODE_HASH
    assert sys.version_info[:2] == (3, 14)
    assert exchange_calendars.__version__ == "4.13.2"


def test_preflight_does_not_import_exit_simulator_or_statistics() -> None:
    source = Path(__file__).parents[1].joinpath("structural_preflight.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert "simulator" not in imports
    assert "statistics" not in imports
    assert "replay_signal" not in source
    assert "evaluate_family" not in source


def test_signal_and_entry_capacity_are_separate_and_canceled_signal_consumes_day() -> None:
    schedule = synthetic_schedule(2)
    frame = synthetic_frame(schedule)
    set_m01(frame, schedule, direction=1, j=12)
    day = schedule[-1].session_date
    set_bar(frame, day, 13, open=100.1, high=100.2, low=100.0, close=100.1)
    set_bar(frame, day, 14, open=99.6, high=100.0, low=99.3, close=99.8)
    data = qualify_ohlc(frame, schedule, expected_session_count=2)
    structural, _, _ = build_structural_evidence(data)
    m01 = structural["mechanisms"]["P4_M01_ALL"]
    assert m01["complete_signal_capacity"] == "BELOW_MINIMUM_CAPACITY"
    assert m01["entry_eligible_capacity"] == "ZERO_EVENT"
    assert m01["daily_entitlement"] == "FIRST_COMPLETE_SIGNAL_CONSUMES_DAY"
    assert structural["counts_disclosed"] is False


def test_zero_events_keep_all_three_primary_hypotheses() -> None:
    data = qualified(synthetic_schedule(2))
    structural, overlap, _ = build_structural_evidence(data)
    assert tuple(structural["mechanisms"]) == FAMILY
    assert all(item["complete_signal_capacity"] == "ZERO_EVENT" for item in structural["mechanisms"].values())
    assert all(item["category"] == "OVERLAP_NOT_COMPUTABLE" for item in overlap["pairs"])


def test_entry_assessment_reads_only_next_open_and_enforces_four_bp_boundary() -> None:
    data = qualified(synthetic_schedule(2))
    day = data.schedule[-1].session_date
    row = data.session(day).reset_index(drop=True).iloc[12]
    exact = Signal("P4_M01_ALL", day, 12, int(row["global_pos"]), str(row["time_et"]), 1, 99.0, "FIXED_PRICE", 100.04, 6, {})
    assert assess_entry(data, exact).reason == "NON_POSITIVE_NET_TARGET"


def test_jaccard_exact_point_eight_is_blocked_and_bar_distance_boundary_is_inclusive() -> None:
    left = [_signal("P4_M01_ALL", f"2025-10-{index + 1:02d}", 10) for index in range(4)]
    right = [_signal("P4_M02_ALL", f"2025-10-{index + 1:02d}", 11) for index in range(4)]
    right.append(_signal("P4_M02_ALL", "2025-10-10", 10))
    result = pair_overlap(left, right)
    assert result.jaccard == pytest.approx(0.80)
    assert result.status == "HIGH_OVERLAP"


def test_registration_or_source_hash_mismatch_blocks_execution(tmp_path: Path) -> None:
    registration = verify_preflight_identity()
    registration["preflight_source_sha256"] = "0" * 64
    altered = tmp_path / "preflight_registration.json"
    altered.write_text(json.dumps(registration), encoding="utf-8")
    with pytest.raises(StructuralPreflightError, match="PREFLIGHT_SOURCE_HASH_MISMATCH"):
        verify_preflight_identity(altered, verify_git=False)


def test_one_shot_attempt_directory_rejects_second_claim(tmp_path: Path) -> None:
    output = tmp_path / "phase4_structural_v1"
    claim_attempt(output)
    with pytest.raises(StructuralPreflightError, match="ATTEMPT_ALREADY_EXISTS"):
        claim_attempt(output)


def test_missing_bar_remains_global_data_gate_failure() -> None:
    schedule = synthetic_schedule(1)
    frame = synthetic_frame(schedule).drop(index=20).reset_index(drop=True)
    with pytest.raises(Phase4ContractError, match="DATA_INCOMPLETE"):
        qualify_ohlc(frame, schedule, expected_session_count=1)


def test_structural_machine_output_has_no_performance_fields() -> None:
    structural, overlap, _ = build_structural_evidence(qualified(synthetic_schedule(2)))
    serialized = json.dumps({"structural": structural, "overlap": overlap}, sort_keys=True).lower()
    for forbidden in ("net_return", "profit_factor", "pnl", "bootstrap", "trade_log", "strategy_results"):
        assert forbidden not in serialized
