from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from factor_research.phase4_mechanism_study.contracts import FAMILY, Phase4ContractError
from factor_research.phase4_mechanism_study.mechanisms import scan_all
from factor_research.phase4_mechanism_study.phase4_train_runner import (
    ATTEMPT_ID,
    Phase4TrainError,
    _artifact_manifest,
    build_robustness,
    build_statistics_gate,
    build_strategy_results,
    claim_attempt,
    execute_research,
    main,
    runner_source_hash,
    verify_train_identity,
)
from factor_research.phase4_mechanism_study.simulator import replay_scan
from factor_research.phase4_mechanism_study.volatility import qualify_ohlc

from .conftest import set_bar, synthetic_frame, synthetic_schedule


def _full_family_data():
    schedule = synthetic_schedule(25)
    frame = synthetic_frame(schedule)

    m06_day = schedule[22].session_date
    set_bar(frame, m06_day, 0, open=102.0, high=102.5, low=101.5, close=102.0)
    set_bar(frame, m06_day, 1, open=101.6, high=101.7, low=100.9, close=101.0)

    m01_day = schedule[23].session_date
    set_bar(frame, m01_day, 12, open=99.6, high=100.0, low=99.3, close=99.8)
    set_bar(frame, m01_day, 13, open=99.8, high=100.1, low=99.7, close=99.9)

    m02_day = schedule[24].session_date
    indices = frame.index[frame["session_date"].eq(m02_day)]
    frame.loc[indices[18:24], ["open", "high", "low", "close"]] = [100.0, 100.2, 99.8, 100.0]
    set_bar(frame, m02_day, 24, open=100.0, high=101.5, low=99.9, close=101.5)
    set_bar(frame, m02_day, 25, open=100.0, high=100.5, low=99.9, close=100.4)
    return qualify_ohlc(frame, schedule, expected_session_count=len(schedule))


def _phase42_capacity() -> dict:
    return {
        "mechanisms": {
            "P4_M01_ALL": {"complete_signal_capacity": "CAPACITY_OK"},
            "P4_M02_ALL": {"complete_signal_capacity": "BELOW_MINIMUM_CAPACITY"},
            "P4_M06_ALL": {"complete_signal_capacity": "BELOW_MINIMUM_CAPACITY"},
        }
    }


def test_full_family_enters_one_orchestration_and_matches_independent_replay() -> None:
    data = _full_family_data()
    bundle = execute_research(data, expected_days=len(data.schedule))
    assert tuple(bundle.statistics.summary["hypothesis_id"]) == FAMILY
    assert set(bundle.signal_audit.loc[bundle.signal_audit["signal_present"], "hypothesis_id"]) == set(FAMILY)
    assert len(bundle.signal_audit) == len(data.schedule) * 3
    for hypothesis_id, session_date in (
        ("P4_M06_ALL", data.schedule[22].session_date),
        ("P4_M01_ALL", data.schedule[23].session_date),
        ("P4_M02_ALL", data.schedule[24].session_date),
    ):
        scan = scan_all(data, session_date)[hypothesis_id]
        independent = replay_scan(data, scan)
        row = bundle.signal_audit.loc[
            bundle.signal_audit["hypothesis_id"].eq(hypothesis_id)
            & bundle.signal_audit["session_date"].eq(session_date)
        ].iloc[0]
        assert row["replay_status"] == independent.status
        if independent.exit_reason_stop_first is None:
            assert pd.isna(row["exit_reason_stop_first"])
        else:
            assert row["exit_reason_stop_first"] == independent.exit_reason_stop_first


def test_canceled_signal_remains_audit_only_and_does_not_become_zero_return() -> None:
    schedule = synthetic_schedule(2)
    frame = synthetic_frame(schedule)
    day = schedule[-1].session_date
    set_bar(frame, day, 12, open=99.6, high=100.0, low=99.3, close=99.8)
    set_bar(frame, day, 13, open=100.1, high=100.2, low=100.0, close=100.1)
    data = qualify_ohlc(frame, schedule, expected_session_count=2)
    bundle = execute_research(data, expected_days=2)
    audit = bundle.signal_audit.loc[
        bundle.signal_audit["hypothesis_id"].eq("P4_M01_ALL")
        & bundle.signal_audit["session_date"].eq(day)
    ].iloc[0]
    assert audit["replay_status"] == "SIGNAL_CANCELED"
    assert audit["cancellation_reason"] == "INVALID_TARGET_GEOMETRY"
    assert bundle.trade_log.loc[bundle.trade_log["hypothesis_id"].eq("P4_M01_ALL")].empty


def test_reveal_hook_orders_signal_boundary_before_return_boundary() -> None:
    boundaries: list[str] = []
    data = _full_family_data()
    execute_research(data, expected_days=len(data.schedule), reveal_hook=boundaries.append)
    assert boundaries == ["SIGNALS_REVEALED_NO_RETURNS", "TRAIN_RETURNS_REVEALED"]


def test_cost_and_path_robustness_are_exact_transformations() -> None:
    data = _full_family_data()
    bundle = execute_research(data, expected_days=len(data.schedule))
    robustness = build_robustness(bundle, {"net_return_4bp": 0.1})
    selected = robustness.loc[
        robustness["hypothesis_id"].eq("P4_M01_ALL")
        & robustness["path_assumption"].eq("STOP_FIRST")
    ].set_index("cost_bps")
    assert selected.loc[2, "mean_net_return"] - selected.loc[4, "mean_net_return"] == pytest.approx(0.0002)
    assert selected.loc[4, "mean_net_return"] - selected.loc[6, "mean_net_return"] == pytest.approx(0.0002)
    assert set(robustness["path_assumption"]) >= {"STOP_FIRST", "TARGET_FIRST"}


def test_frozen_below_capacity_mechanisms_cannot_be_promoted() -> None:
    data = _full_family_data()
    bundle = execute_research(data, expected_days=len(data.schedule))
    results = build_strategy_results(bundle, _phase42_capacity())
    blocked = results.loc[results["hypothesis_id"].isin(["P4_M02_ALL", "P4_M06_ALL"])]
    assert not blocked["candidate"].any()
    assert set(blocked["research_status"]) == {"NO_EVIDENCE_BELOW_MINIMUM_CAPACITY"}


def test_statistics_gate_rejects_unqualified_candidate_and_forbidden_labels() -> None:
    data = _full_family_data()
    bundle = execute_research(data, expected_days=len(data.schedule))
    results = build_strategy_results(bundle, _phase42_capacity())
    bad = results.copy()
    bad.loc[bad["hypothesis_id"].eq("P4_M02_ALL"), "candidate"] = True
    with pytest.raises(Phase4TrainError, match="STATISTICS_GATE_FAILED"):
        build_statistics_gate(bundle, bad, {"runner_source_sha256": runner_source_hash()})
    bad = results.copy()
    bad.loc[0, "research_status"] = "VALIDATED_EDGE"
    with pytest.raises(Phase4TrainError, match="STATISTICS_GATE_FAILED"):
        build_statistics_gate(bundle, bad, {"runner_source_sha256": runner_source_hash()})


def test_incomplete_or_failed_family_never_emits_a_valid_candidate() -> None:
    data = _full_family_data()
    damaged = replace(data, schedule=data.schedule[:-1])
    with pytest.raises(Phase4TrainError, match="EXECUTION_CALENDAR_MISMATCH"):
        execute_research(damaged, expected_days=len(data.schedule))


def test_claim_attempt_is_one_shot(tmp_path: Path) -> None:
    output = tmp_path / "phase4_train_v1"
    claim_attempt(output)
    with pytest.raises(Phase4TrainError, match="ATTEMPT_ALREADY_EXISTS"):
        claim_attempt(output)


def test_registration_mismatch_fails_before_data_access(tmp_path: Path) -> None:
    bad = {
        "attempt_id": ATTEMPT_ID,
        "runner_version": "WRONG",
    }
    path = tmp_path / "registration.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(Phase4TrainError, match="TRAIN_REGISTRATION_MISMATCH"):
        verify_train_identity(path, verify_git=False, check_attempt=False)


def test_cli_is_disabled_without_exact_one_shot_authorization() -> None:
    with pytest.raises(SystemExit):
        main([])
    with pytest.raises(SystemExit):
        main(["--authorize-one-shot-train", "WRONG"])


def test_manifest_refuses_missing_required_output(tmp_path: Path) -> None:
    with pytest.raises(Phase4TrainError, match="REQUIRED_OUTPUT_MISSING"):
        _artifact_manifest(tmp_path)


def test_statistics_rejects_nonfinite_trade_input_end_to_end() -> None:
    data = _full_family_data()
    bundle = execute_research(data, expected_days=len(data.schedule))
    trade = bundle.trade_log.copy()
    trade.loc[trade.index[0], "gross_return_stop_first"] = float("nan")
    with pytest.raises(Phase4ContractError, match="NONFINITE_STATISTICAL_INPUT"):
        from factor_research.phase4_mechanism_study.statistics import evaluate_family

        evaluate_family(
            trade[["hypothesis_id", "session_date", "gross_return_stop_first"]].rename(
                columns={"gross_return_stop_first": "gross_return"}
            ),
            [spec.session_date for spec in data.schedule],
            expected_days=len(data.schedule),
        )
