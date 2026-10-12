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
