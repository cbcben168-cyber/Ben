from __future__ import annotations

from collections import defaultdict
from statistics import mean, median


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
