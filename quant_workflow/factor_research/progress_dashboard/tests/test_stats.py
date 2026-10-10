from quant_workflow.factor_research.progress_dashboard.stats import compute_train_analysis


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
        assert item["stability"]["paired_days"] == 3
        assert item["stability"]["better_days"] == 3
        assert len(item["daily"]) == 3
        assert len(item["monthly"]) == 2
        assert "overlapping events are not independent samples" in item["limitations"]
