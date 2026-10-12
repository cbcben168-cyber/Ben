from __future__ import annotations

import copy
import math

import numpy as np
import pandas as pd
import pytest

from factor_research.phase3_edge_engine import statistics


def _row(summary: dict) -> dict:
    return {
        "estimate": summary["mean"],
        "se": summary["se"],
        "_cluster_days": summary["_cluster_days"].copy(),
        "_cluster_sums": summary["_cluster_sums"].copy(),
        "_cluster_counts": summary["_cluster_counts"].copy(),
    }


def test_cluster_bootstrap_recomputes_trade_weighted_estimand_with_unequal_counts():
    values = pd.Series([0.01] * 1_000 + [-0.01] * 9)
    days = pd.Series(["D0"] * 1_000 + [f"D{index}" for index in range(1, 10)])
    calendar = [f"D{index}" for index in range(10)]
    summary = statistics._cluster_summary(values, days, "unequal-counts", calendar)
    assert summary["mean"] == pytest.approx(values.mean(), abs=1e-15)
    assert summary["ci_low"] <= summary["mean"] <= summary["ci_high"]
    assert summary["se"] > 0.008
    assert summary["days"] == 10


def test_common_day_indices_preserve_perfect_family_correlation():
    calendar = [f"D{index}" for index in range(10)]
    values = pd.Series([-1.4, -1.0, -0.8, -0.4, -0.1, 0.2, 0.4, 0.8, 1.0, 1.3])
    days = pd.Series(calendar)
    summary = statistics._cluster_summary(values, days, "perfect-correlation", calendar)
    single = [_row(summary)]
    repeated = [copy.deepcopy(_row(summary)) for _ in range(8)]
    statistics._apply_family_adjustment(single, "same-calendar")
    statistics._apply_family_adjustment(repeated, "same-calendar")
    single_critical = (single[0]["simultaneous_ci_high"] - single[0]["estimate"]) / single[0]["se"]
    repeated_critical = (repeated[0]["simultaneous_ci_high"] - repeated[0]["estimate"]) / repeated[0]["se"]
    assert repeated_critical == pytest.approx(single_critical, abs=1e-15)
    assert len({row["raw_p_value"] for row in repeated}) == 1


def test_missing_events_and_different_frequencies_use_one_registered_calendar():
    calendar = [f"D{index}" for index in range(6)]
    first = statistics._cluster_summary(
        pd.Series([0.1, 0.2, -0.1, 0.3]),
        pd.Series(["D0", "D0", "D2", "D4"]),
        "missing-first",
        calendar,
    )
    second = statistics._cluster_summary(
        pd.Series([-0.2, 0.4, 0.1]),
        pd.Series(["D1", "D3", "D5"]),
        "missing-second",
        calendar,
    )
    rows = [_row(first), _row(second)]
    assert rows[0]["_cluster_days"].tolist() == rows[1]["_cluster_days"].tolist() == calendar
    statistics._apply_family_adjustment(rows, "missing-events")
    assert all(np.isfinite(row["raw_p_value"]) for row in rows)


def test_holm_retains_untestable_preregistered_family_members():
    rows = [
        {"raw_p_value": 0.01},
        {"raw_p_value": 0.02},
        {"raw_p_value": np.nan},
        {"raw_p_value": np.nan},
    ]
    statistics._holm(rows)
    assert rows[0]["holm_p_value"] == pytest.approx(0.04)
    assert rows[1]["holm_p_value"] == pytest.approx(0.06)
    assert np.isnan(rows[2]["holm_p_value"])
    assert np.isnan(rows[3]["holm_p_value"])


def test_correlated_null_family_error_and_simultaneous_coverage(monkeypatch):
    monkeypatch.setattr(statistics, "BOOTSTRAP_ITERATIONS", 400)
    replications = 120
    day_count = 60
    hypothesis_count = 6
    correlation = 0.8
    data_rng = np.random.default_rng(20261012)
    family_covered = 0
    holm_rejected = 0
    calendar = [f"D{index:03d}" for index in range(day_count)]
    days = pd.Series(calendar)
    for replication in range(replications):
        common = data_rng.normal(size=(day_count, 1))
        independent = data_rng.normal(size=(day_count, hypothesis_count))
        values = math.sqrt(correlation) * common + math.sqrt(1.0 - correlation) * independent
        rows = []
        for hypothesis in range(hypothesis_count):
            summary = statistics._cluster_summary(
                pd.Series(values[:, hypothesis]),
                days,
                f"null-{replication}-{hypothesis}",
                calendar,
            )
            rows.append(_row(summary))
        statistics._apply_family_adjustment(rows, f"null-family-{replication}")
        family_covered += all(
            row["simultaneous_ci_low"] <= 0 <= row["simultaneous_ci_high"]
            for row in rows
        )
        holm_rejected += any(row["holm_p_value"] < 0.05 for row in rows)
    coverage = family_covered / replications
    family_error_rate = holm_rejected / replications
    assert 0.90 <= coverage <= 0.99
    assert family_error_rate <= 0.10


def _factor_spec(factor_id: str, direction: str):
    from factor_research.phase3_edge_engine.contracts import FactorSpec

    return FactorSpec(
        factor_id=factor_id,
        name_en="test",
        name_zh="test",
        category="TEST",
        mechanism="test",
        formula="test",
        parameters="test",
        as_of="completed_5m_close",
        direction=direction,
        event_unit="TEST",
        data_requirements="OHLC",
        independent_unit="TRADING_DAY",
        strategy_role="test",
        eligibility="ELIGIBLE_5M",
        attempt_version="TEST",
    )


@pytest.mark.parametrize("market_baseline", [0.01, -0.01, 0.0])
def test_factor_baseline_is_direction_consistent_for_long_short_and_regime(market_baseline):
    data = pd.DataFrame({
        "is_train": [True, True],
        "session_date": ["D0", "D1"],
        "return_h3": [market_baseline, market_baseline],
        "return_h6": [market_baseline, market_baseline],
        "return_h12": [market_baseline, market_baseline],
    })
    events = pd.DataFrame([
        {"factor_id": "F001", "direction": 1, "session_date": "D0", "return_h3": 0.02, "return_h6": 0.02, "return_h12": 0.02},
        {"factor_id": "F007", "direction": -1, "session_date": "D0", "return_h3": -0.02, "return_h6": -0.02, "return_h12": -0.02},
        {"factor_id": "F012", "direction": 1, "session_date": "D0", "return_h3": -0.02, "return_h6": -0.02, "return_h12": -0.02},
    ])
    result = statistics.factor_results(
        events,
        data,
        [_factor_spec("F001", "LONG"), _factor_spec("F007", "BOTH"), _factor_spec("F012", "REGIME")],
    )
    long = result[(result["factor_id"] == "F001") & (result["horizon_minutes"] == 15)].iloc[0]
    short = result[(result["factor_id"] == "F007") & (result["horizon_minutes"] == 15)].iloc[0]
    regime = result[(result["factor_id"] == "F012") & (result["horizon_minutes"] == 15)].iloc[0]
    assert long["directional_mean"] == pytest.approx(0.02)
    assert long["baseline_directional"] == pytest.approx(market_baseline)
    assert long["increment"] == pytest.approx(0.02 - market_baseline)
    assert short["raw_mean"] == pytest.approx(-0.02)
    assert short["directional_mean"] == pytest.approx(0.02)
    assert short["baseline_directional"] == pytest.approx(-market_baseline)
    assert short["increment"] == pytest.approx(0.02 + market_baseline)
    assert np.isnan(regime["baseline_directional"])
    assert regime["baseline_mean"] == pytest.approx(market_baseline)
    assert regime["increment"] == pytest.approx(-0.02 - market_baseline)
    assert set(result["inference_target"]) == {"DIRECTIONAL_MEAN_VS_ZERO"}


def test_short_synthetic_example_is_plus_three_percent_increment():
    data = pd.DataFrame({
        "is_train": [True, True],
        "session_date": ["D0", "D1"],
        "return_h3": [0.01, 0.01],
        "return_h6": [0.01, 0.01],
        "return_h12": [0.01, 0.01],
    })
    events = pd.DataFrame([{
        "factor_id": "F007", "direction": -1, "session_date": "D0",
        "return_h3": -0.02, "return_h6": -0.02, "return_h12": -0.02,
    }])
    row = statistics.factor_results(events, data, [_factor_spec("F007", "BOTH")]).iloc[0]
    assert row["directional_mean"] == pytest.approx(0.02)
    assert row["baseline_raw_market"] == pytest.approx(0.01)
    assert row["baseline_directional"] == pytest.approx(-0.01)
    assert row["increment"] == pytest.approx(0.03)


def test_no_valid_factor_events_remain_insufficient_without_false_pass_evidence():
    data = pd.DataFrame({
        "is_train": [True, True],
        "session_date": ["D0", "D1"],
        "return_h3": [0.01, 0.01],
        "return_h6": [0.01, 0.01],
        "return_h12": [0.01, 0.01],
    })
    events = pd.DataFrame([{
        "factor_id": "F007", "direction": -1, "session_date": "D0",
        "return_h3": np.nan, "return_h6": np.nan, "return_h12": np.nan,
    }])
    result = statistics.factor_results(events, data, [_factor_spec("F007", "BOTH")])
    assert (result["events"] == 0).all()
    assert (result["sample_status"] == "INSUFFICIENT_SAMPLE").all()
    assert result["directional_mean"].isna().all()
    assert result["increment"].isna().all()
    assert result["raw_p_value"].isna().all()


@pytest.fixture(scope="module")
def gate_state(phase3_state):
    from factor_research.phase3_edge_engine.statistics import (
        factor_results,
        regime_time_results,
        strategy_results,
        test_registry,
    )

    factor = factor_results(phase3_state["events"], phase3_state["features"], phase3_state["factor_specs"])
    calendar = list(phase3_state["features"].loc[phase3_state["features"]["is_train"], "session_date"].drop_duplicates())
    strategy = strategy_results(phase3_state["trades"], calendar)
    regime = regime_time_results(phase3_state["trades"], phase3_state["events"])
    tests = test_registry(factor, strategy, regime)
    return {
        "factor": factor,
        "strategy": strategy,
        "regime": regime,
        "tests": tests,
        "factor_specs": phase3_state["factor_specs"],
        "strategy_specs": phase3_state["strategy_specs"],
        "factor_keys": {
            (str(row.factor_id), str(row.direction), int(row.horizon_minutes))
            for row in factor.itertuples()
        },
        "strategy_keys": {
            (str(row.variant_id), str(row.direction)) for row in strategy.itertuples()
        },
    }


def _run_gate(state, factor=None, strategy=None, tests=None):
    return statistics.statistics_integrity_gate(
        state["factor"] if factor is None else factor,
        state["strategy"] if strategy is None else strategy,
        state["regime"],
        state["factor_specs"],
        state["strategy_specs"],
        state["tests"] if tests is None else tests,
        state["factor_keys"],
        state["strategy_keys"],
    )


def test_statistics_gate_accepts_the_frozen_valid_family(gate_state):
    gate = _run_gate(gate_state)
    assert gate["status"] == "STATISTICS_PASS"
    assert gate["checks_failed"] == 0


def test_statistics_gate_rejects_wrong_short_baseline_sign(gate_state):
    factor = gate_state["factor"].copy(deep=True)
    index = factor.index[factor["direction"] == "SHORT"][0]
    factor.loc[index, "baseline_directional"] = factor.loc[index, "baseline_raw_market"]
    factor.loc[index, "baseline_mean"] = factor.loc[index, "baseline_raw_market"]
    assert _run_gate(gate_state, factor=factor)["status"] == "STATISTICS_FAIL"


def test_statistics_gate_rejects_wrong_increment(gate_state):
    factor = gate_state["factor"].copy(deep=True)
    factor.loc[factor.index[0], "increment"] += 0.01
    assert _run_gate(gate_state, factor=factor)["status"] == "STATISTICS_FAIL"


def test_statistics_gate_rejects_missing_required_row(gate_state):
    factor = gate_state["factor"].iloc[1:].copy()
    assert _run_gate(gate_state, factor=factor)["status"] == "STATISTICS_FAIL"


def test_statistics_gate_rejects_illegal_pvalue(gate_state):
    factor = gate_state["factor"].copy(deep=True)
    factor.loc[factor.index[0], "raw_p_value"] = 1.5
    assert _run_gate(gate_state, factor=factor)["status"] == "STATISTICS_FAIL"


def test_statistics_gate_rejects_invalid_simultaneous_interval(gate_state):
    factor = gate_state["factor"].copy(deep=True)
    index = factor.index[0]
    factor.loc[index, "simultaneous_ci_low"] = factor.loc[index, "directional_mean"] + 0.01
    assert _run_gate(gate_state, factor=factor)["status"] == "STATISTICS_FAIL"


def test_statistics_gate_rejects_incomplete_registered_family(gate_state):
    tests = gate_state["tests"].copy(deep=True)
    tests.loc[tests["family"] == "FACTOR_PREDICTION", "actual_tests"] -= 1
    assert _run_gate(gate_state, tests=tests)["status"] == "STATISTICS_FAIL"
