from __future__ import annotations

from collections import defaultdict
import hashlib
import random
from statistics import mean, median, pstdev


def compute_statistics(signals: list[dict], labels: list[dict]) -> list[dict]:
    factor_by_signal = {item["signal_id"]: item["factor_value"] for item in signals}
    grouped: dict[tuple[int, str], list[float]] = defaultdict(list)
    for item in labels:
        horizon = int(item["horizon_minutes"])
        value = float(item["forward_return"])
        cohort = factor_by_signal[item["signal_id"]]
        grouped[(horizon, "ALL")].append(value)
        grouped[(horizon, cohort)].append(value)

    rows: list[dict] = []
    for horizon in (15, 30, 60):
        baseline_values = grouped.get((horizon, "ALL"), [])
        baseline_mean = mean(baseline_values) if baseline_values else None
        for cohort in ("ALL", "PASS", "FAIL"):
            values = grouped.get((horizon, cohort), [])
            current_mean = mean(values) if values else None
            rows.append(
                {
                    "horizon_minutes": horizon,
                    "cohort": cohort,
                    "n": len(values),
                    "mean_return": current_mean,
                    "median_return": median(values) if values else None,
                    "positive_rate": (
                        sum(value > 0 for value in values) / len(values) if values else None
                    ),
                    "baseline_mean": baseline_mean,
                    "edge_bps": (
                        (current_mean - baseline_mean) * 10000
                        if current_mean is not None and baseline_mean is not None
                        else None
                    ),
                }
            )
    return rows


def histogram(values: list[float], bins: int = 9) -> list[dict]:
    if not values:
        return []
    low, high = min(values), max(values)
    if low == high:
        return [{"low": low, "high": high, "count": len(values)}]
    width = (high - low) / bins
    counts = [0] * bins
    for value in values:
        index = min(int((value - low) / width), bins - 1)
        counts[index] += 1
    return [
        {"low": low + index * width, "high": low + (index + 1) * width, "count": count}
        for index, count in enumerate(counts)
    ]


def _summary(values: list[float]) -> dict:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "median": None,
            "positive_rate": None,
            "stddev": None,
            "p05": None,
            "p25": None,
            "p75": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    return {
        "n": len(values),
        "mean": mean(values),
        "median": median(values),
        "positive_rate": sum(value > 0 for value in values) / len(values),
        "stddev": pstdev(values),
        "p05": _percentile(values, 0.05),
        "p25": _percentile(values, 0.25),
        "p75": _percentile(values, 0.75),
        "p95": _percentile(values, 0.95),
        "min": min(values),
        "max": max(values),
    }


def _difference(pass_values: list[float], fail_values: list[float]) -> float | None:
    if not pass_values or not fail_values:
        return None
    return (mean(pass_values) - mean(fail_values)) * 10000


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def compute_train_analysis(
    signals: list[dict],
    labels: list[dict],
    *,
    seed_key: str,
    bootstrap_replicates: int = 5000,
) -> list[dict]:
    """Compute pre-registered TRAIN diagnostics without treating events as independent."""
    signal_by_id = {item["signal_id"]: item for item in signals}
    labels_by_horizon: dict[int, list[dict]] = defaultdict(list)
    for item in labels:
        labels_by_horizon[int(item["horizon_minutes"])].append(item)

    results: list[dict] = []
    for horizon_minutes, horizon_bars in ((15, 3), (30, 6), (60, 12)):
        observations: list[dict] = []
        for label in labels_by_horizon.get(horizon_minutes, []):
            signal = signal_by_id[label["signal_id"]]
            observations.append(
                {
                    "day": str(signal["signal_time_et"])[:10],
                    "month": str(signal["signal_time_et"])[:7],
                    "time": str(signal["signal_time_et"])[11:16],
                    "cohort": signal["factor_value"],
                    "value": float(label["forward_return"]),
                    "signal_id": signal["signal_id"],
                }
            )
        observations.sort(key=lambda item: (item["day"], item["time"], item["signal_id"]))

        daily_groups: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: {"ALL": [], "PASS": [], "FAIL": []}
        )
        monthly_groups: dict[str, dict[str, list[float]]] = defaultdict(
            lambda: {"ALL": [], "PASS": [], "FAIL": []}
        )
        day_positions: dict[str, int] = defaultdict(int)
        phase_groups: list[dict[str, list[float]]] = [
            {"ALL": [], "PASS": [], "FAIL": []} for _ in range(horizon_bars)
        ]
        for item in observations:
            value = item["value"]
            cohort = item["cohort"]
            for groups, key in ((daily_groups, item["day"]), (monthly_groups, item["month"])):
                groups[key]["ALL"].append(value)
                groups[key][cohort].append(value)
            position = day_positions[item["day"]]
            day_positions[item["day"]] += 1
            phase = position % horizon_bars
            phase_groups[phase]["ALL"].append(value)
            phase_groups[phase][cohort].append(value)

        daily: list[dict] = []
        cluster_rows: list[dict] = []
        for day in sorted(daily_groups):
            groups = daily_groups[day]
            pass_values = groups["PASS"]
            fail_values = groups["FAIL"]
            difference_bps = _difference(pass_values, fail_values)
            daily.append(
                {
                    "day": day,
                    "baseline": _summary(groups["ALL"]),
                    "pass": _summary(pass_values),
                    "fail": _summary(fail_values),
                    "pass_fail_diff_bps": difference_bps,
                }
            )
            cluster_rows.append(
                {
                    "pass_sum": sum(pass_values),
                    "pass_n": len(pass_values),
                    "fail_sum": sum(fail_values),
                    "fail_n": len(fail_values),
                }
            )

        monthly: list[dict] = []
        for month in sorted(monthly_groups):
            groups = monthly_groups[month]
            monthly.append(
                {
                    "month": month,
                    "baseline": _summary(groups["ALL"]),
                    "pass": _summary(groups["PASS"]),
                    "fail": _summary(groups["FAIL"]),
                    "pass_fail_diff_bps": _difference(groups["PASS"], groups["FAIL"]),
                }
            )

        non_overlap_phases: list[dict] = []
        for phase, groups in enumerate(phase_groups):
            non_overlap_phases.append(
                {
                    "phase": phase,
                    "horizon_bars": horizon_bars,
                    "baseline": _summary(groups["ALL"]),
                    "pass": _summary(groups["PASS"]),
                    "fail": _summary(groups["FAIL"]),
                    "pass_fail_diff_bps": _difference(groups["PASS"], groups["FAIL"]),
                }
            )

        bootstrap_values: list[float] = []
        if cluster_rows:
            seed_material = f"{seed_key}|{horizon_minutes}|TRAIN_CLUSTER_BOOTSTRAP_V1"
            seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
            rng = random.Random(seed)
            cluster_count = len(cluster_rows)
            for _ in range(bootstrap_replicates):
                pass_sum = 0.0
                pass_n = 0
                fail_sum = 0.0
                fail_n = 0
                for _ in range(cluster_count):
                    row = cluster_rows[rng.randrange(cluster_count)]
                    pass_sum += row["pass_sum"]
                    pass_n += row["pass_n"]
                    fail_sum += row["fail_sum"]
                    fail_n += row["fail_n"]
                if pass_n and fail_n:
                    bootstrap_values.append((pass_sum / pass_n - fail_sum / fail_n) * 10000)

        paired_daily = [
            item["pass_fail_diff_bps"]
            for item in daily
            if item["pass_fail_diff_bps"] is not None
        ]
        monthly_differences = [
            item["pass_fail_diff_bps"]
            for item in monthly
            if item["pass_fail_diff_bps"] is not None
        ]
        all_pass_days = sum(item["fail"]["n"] == 0 and item["pass"]["n"] > 0 for item in daily)
        all_fail_days = sum(item["pass"]["n"] == 0 and item["fail"]["n"] > 0 for item in daily)
        results.append(
            {
                "analysis_version": "TRAIN_ROBUSTNESS_V1",
                "horizon_minutes": horizon_minutes,
                "trading_day_clusters": len(cluster_rows),
                "daily": daily,
                "monthly": monthly,
                "non_overlap_phases": non_overlap_phases,
                "cluster_bootstrap": {
                    "unit": "trading_day",
                    "replicates_requested": bootstrap_replicates,
                    "replicates_valid": len(bootstrap_values),
                    "ci_low_bps": _percentile(bootstrap_values, 0.025),
                    "median_bps": _percentile(bootstrap_values, 0.5),
                    "ci_high_bps": _percentile(bootstrap_values, 0.975),
                    "seed_method": "sha256(run_instance_id|horizon|method)",
                },
                "stability": {
                    "paired_days": len(paired_daily),
                    "better_days": sum(value > 0 for value in paired_daily),
                    "worse_days": sum(value < 0 for value in paired_daily),
                    "positive_months": sum(value > 0 for value in monthly_differences),
                    "negative_months": sum(value < 0 for value in monthly_differences),
                    "all_pass_days": all_pass_days,
                    "all_fail_days": all_fail_days,
                    "max_abs_daily_diff_bps": (
                        max(abs(value) for value in paired_daily) if paired_daily else None
                    ),
                },
                "limitations": [
                    "overlapping events are not independent samples",
                    "bootstrap resamples whole trading days",
                    "all non-overlapping phases are reported without phase selection",
                    "TRAIN evidence cannot establish Validation or OOS support",
                ],
            }
        )
    return results
