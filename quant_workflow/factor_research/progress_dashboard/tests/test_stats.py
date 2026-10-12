import pytest

from quant_workflow.factor_research.progress_dashboard.stats import (
    compute_distribution_statistics,
    compute_signal_redundancy,
    compute_statistics,
    compute_train_analysis,
)


def sample_data():
    signals = []
    labels = []
    for day_index, day in enumerate(("2025-10-01", "2025-10-02", "2025-11-03")):
        for position in range(12):
            signal_id = f"D{day_index}S{position}"
            cohort = "PASS" if position % 2 == 0 else "FAIL"
            signals.append(
                {
                    "signal_id": signal_id,
                    "signal_time_et": f"{day}T{9 + (35 + position * 5) // 60:02d}:{(35 + position * 5) % 60:02d}:00",
                    "factor_value": cohort,
                }
            )
            for horizon in (15, 30, 60):
                direction = 0.001 if cohort == "PASS" else -0.0005
                labels.append(
                    {
                        "signal_id": signal_id,
                        "horizon_minutes": horizon,
                        "forward_return": direction + day_index * 0.0001,
                    }
                )
    return signals, labels


def test_train_analysis_reports_all_phases_cluster_bootstrap_and_stability():
    signals, labels = sample_data()
    first = compute_train_analysis(signals, labels, seed_key="RUN", bootstrap_replicates=200)
    second = compute_train_analysis(signals, labels, seed_key="RUN", bootstrap_replicates=200)
    assert first == second
    assert [item["horizon_minutes"] for item in first] == [15, 30, 60]
    assert [len(item["non_overlap_phases"]) for item in first] == [3, 6, 12]
    for item in first:
        assert item["trading_day_clusters"] == 3
        assert item["cluster_bootstrap"]["replicates_valid"] == 200
        assert item["cluster_bootstrap"]["ci_low_bps"] > 0
        assert item["cluster_bootstrap"]["bonferroni_ci_low_bps"] > 0
        assert item["stability"]["paired_days"] == 3
        assert item["stability"]["better_days"] == 3
        assert len(item["daily"]) == 3
        assert len(item["monthly"]) == 2
        assert item["same_day_time_bucket"]["strata_matched"] == 6
        assert item["same_day_time_bucket"]["mean_stratum_diff_bps"] == pytest.approx(15.0)
        assert item["same_day_time_bucket"]["fixed_effect_diff_bps"] == pytest.approx(15.0)
        assert "overlapping events are not independent samples" in item["limitations"]


def test_distribution_statistics_include_quantiles_without_changing_persisted_schema():
    signals = [
        {"signal_id": "A", "factor_value": "PASS"},
        {"signal_id": "B", "factor_value": "PASS"},
    ]
    labels = [
        {"signal_id": "A", "horizon_minutes": 15, "forward_return": -0.01},
        {"signal_id": "B", "horizon_minutes": 15, "forward_return": 0.03},
    ]

    persisted = compute_statistics(signals, labels)
    rows = compute_distribution_statistics(signals, labels)
    passed = next(row for row in rows if row["horizon_minutes"] == 15 and row["cohort"] == "PASS")
    failed = next(row for row in rows if row["horizon_minutes"] == 15 and row["cohort"] == "FAIL")
    assert passed["median"] == pytest.approx(0.01)
    assert passed["p05"] == pytest.approx(-0.008)
    assert passed["p95"] == pytest.approx(0.028)
    assert passed["min"] == -0.01
    assert passed["max"] == 0.03
    assert failed["n"] == 0
    assert failed["p05"] is None
    assert list(persisted[0]) == [
        "horizon_minutes",
        "cohort",
        "n",
        "mean_return",
        "median_return",
        "positive_rate",
        "baseline_mean",
        "edge_bps",
    ]


def test_signal_redundancy_reports_perfect_duplicate_and_inverse():
    states = {
        "F001": {"1": "PASS", "2": "PASS", "3": "FAIL", "4": "FAIL"},
        "F002": {"1": "PASS", "2": "PASS", "3": "FAIL", "4": "FAIL"},
        "F003": {"1": "FAIL", "2": "FAIL", "3": "PASS", "4": "PASS"},
    }

    rows = compute_signal_redundancy(states)
    duplicate = next(row for row in rows if row["factor_a"] == "F001" and row["factor_b"] == "F002")
    inverse = next(row for row in rows if row["factor_a"] == "F001" and row["factor_b"] == "F003")
    assert duplicate["phi"] == pytest.approx(1.0)
    assert duplicate["agreement_rate"] == 1.0
    assert duplicate["pass_jaccard"] == 1.0
    assert inverse["phi"] == pytest.approx(-1.0)
    assert inverse["agreement_rate"] == 0.0


def test_signal_redundancy_rejects_unaligned_signal_ids():
    with pytest.raises(ValueError, match="not aligned"):
        compute_signal_redundancy(
            {"F001": {"1": "PASS"}, "F002": {"2": "PASS"}}
        )
