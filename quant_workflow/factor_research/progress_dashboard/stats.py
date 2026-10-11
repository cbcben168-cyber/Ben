from __future__ import annotations

from collections import defaultdict
import hashlib
import random
from statistics import mean, median, pstdev
from itertools import combinations


def compute_strategy_metrics(
    trades: list[dict], *, bootstrap_replicates: int = 2000, seed_key: str = "strategy-v3"
) -> list[dict]:
    """Summarize executable trade records with trading-day cluster uncertainty."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for trade in trades:
        grouped[(str(trade["strategy_id"]), str(trade["direction"]))].append(trade)
    rows: list[dict] = []
    for (strategy_id, direction), items in sorted(grouped.items()):
        items.sort(key=lambda item: (str(item["trade_date_et"]), str(item.get("exit_time_et", item["entry_time_et"]))))
        returns = [float(item["net_return"]) for item in items]
        gross_profits = sum(value for value in returns if value > 0)
        gross_losses = -sum(value for value in returns if value < 0)
        equity = 1.0
        peak = 1.0
        max_drawdown = 0.0
        for value in returns:
            equity *= 1.0 + value
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak)
        by_day: dict[str, list[float]] = defaultdict(list)
        by_month: dict[str, list[float]] = defaultdict(list)
        for item in items:
            day = str(item["trade_date_et"])
            by_day[day].append(float(item["net_return"]))
            by_month[day[:7]].append(float(item["net_return"]))
        rng = random.Random(int(hashlib.sha256(seed_key.encode()).hexdigest()[:16], 16))
        days = sorted(by_day)
        bootstrap_means: list[float] = []
        if days:
            for _ in range(bootstrap_replicates):
                sampled = [days[rng.randrange(len(days))] for _ in days]
                sample = [value for day in sampled for value in by_day[day]]
                bootstrap_means.append(mean(sample))
        rows.append(
            {
                "strategy_id": strategy_id,
                "direction": direction,
                "trade_count": len(items),
                "trading_days": len(days),
                "net_mean": mean(returns) if returns else None,
                "net_median": median(returns) if returns else None,
                "positive_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
                "profit_factor": gross_profits / gross_losses if gross_losses else None,
                "max_drawdown": max_drawdown,
                "mfe_mean": mean(float(item["mfe"]) for item in items) if items else None,
                "mae_mean": mean(float(item["mae"]) for item in items) if items else None,
                "ambiguous_count": sum(bool(item["ambiguous"]) for item in items),
                "target_count": sum(item["exit_reason"] == "TARGET" for item in items),
                "stop_count": sum(item["exit_reason"] == "STOP" for item in items),
                "timeout_count": sum(item["exit_reason"] == "TIME" for item in items),
                "cluster_ci_low": _percentile(bootstrap_means, 0.025),
                "cluster_ci_high": _percentile(bootstrap_means, 0.975),
                "bootstrap_replicates": bootstrap_replicates,
                "monthly": [
                    {"month": month, "trades": len(values), "net_mean": mean(values), "net_sum": sum(values)}
                    for month, values in sorted(by_month.items())
                ],
            }
        )
    return rows


def compute_strategy_inference(
    signals: list[dict],
    trades: list[dict],
    *,
    bootstrap_replicates: int = 2000,
    seed_key: str = "strategy-v3.1",
) -> dict:
    """Execute every V3.1 preregistered family with day-cluster resampling."""
    baseline_signals = [item for item in signals if item["candidate_id"] == "F012"]
    study_days = sorted({str(item["signal_time_et"])[:10] for item in baseline_signals})
    trade_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for item in trades:
        trade_groups[(str(item["strategy_id"]), str(item["direction"]))].append(item)

    specs: list[dict] = []

    def add_value_spec(
        family: str,
        test_id: str,
        items: list[dict],
        value_fn,
        match_fn,
        *,
        min_n: int,
        min_days: int,
        target: str,
    ) -> None:
        by_day: dict[str, list[float]] = defaultdict(list)
        matched = []
        for item in items:
            day = str(item["trade_date_et"])
            by_day[day].append(float(value_fn(item)))
            if match_fn(item):
                matched.append(item)
        day_totals = {
            day: (sum(values), len(values)) for day, values in by_day.items()
        }

        def estimator(sampled_days: list[str]) -> float | None:
            total = 0.0
            count = 0
            for day in sampled_days:
                day_total, day_count = day_totals.get(day, (0.0, 0))
                total += day_total
                count += day_count
            return total / count if count else None

        specs.append(
            {
                "family": family,
                "test_id": test_id,
                "target": target,
                "estimator": estimator,
                "sample_count": len(matched),
                "trading_days": len({str(item["trade_date_et"]) for item in matched}),
                "baseline_count": len(items),
                "coverage": len(matched) / len(items) if items else 0.0,
                "min_n": min_n,
                "min_days": min_days,
            }
        )

    baseline_by_horizon: dict[int, dict[str, list[float]]] = {}
    for horizon, key in ((15, "r15"), (30, "r30"), (60, "r60")):
        values: dict[str, list[float]] = defaultdict(list)
        for item in baseline_signals:
            if item.get(key) is not None:
                values[str(item["signal_time_et"])[:10]].append(float(item[key]))
        baseline_by_horizon[horizon] = values

    for candidate_id in ("F007", "F008", "F009", "F010", "F011"):
        for direction in ("LONG", "SHORT"):
            sign = -1.0 if direction == "SHORT" else 1.0
            candidate_items = [
                item for item in signals
                if item["candidate_id"] == candidate_id and item["direction"] == direction
            ]
            for horizon, key in ((15, "r15"), (30, "r30"), (60, "r60")):
                candidate_by_day: dict[str, list[float]] = defaultdict(list)
                for item in candidate_items:
                    if item.get(key) is not None:
                        candidate_by_day[str(item["signal_time_et"])[:10]].append(float(item[key]))
                market_by_day = baseline_by_horizon[horizon]
                candidate_totals = {
                    day: (sum(values), len(values))
                    for day, values in candidate_by_day.items()
                }
                market_totals = {
                    day: (sum(values), len(values))
                    for day, values in market_by_day.items()
                }

                def estimator(
                    sampled_days: list[str],
                    candidate_totals=candidate_totals,
                    market_totals=market_totals,
                    sign=sign,
                ) -> float | None:
                    selected_sum = selected_count = 0
                    market_sum = market_count = 0
                    for day in sampled_days:
                        day_sum, day_count = candidate_totals.get(day, (0.0, 0))
                        selected_sum += day_sum
                        selected_count += day_count
                        day_sum, day_count = market_totals.get(day, (0.0, 0))
                        market_sum += day_sum
                        market_count += day_count
                    if not selected_count or not market_count:
                        return None
                    return sign * (
                        selected_sum / selected_count - market_sum / market_count
                    )

                opening = candidate_id in {"F009", "F011"}
                specs.append(
                    {
                        "family": "CANDIDATE_SCREEN",
                        "test_id": f"{candidate_id}_{direction}_{horizon}",
                        "target": "directional_increment_vs_unconditional_market",
                        "estimator": estimator,
                        "sample_count": len(candidate_items),
                        "trading_days": len(
                            {str(item["signal_time_et"])[:10] for item in candidate_items}
                        ),
                        "baseline_count": len(baseline_signals),
                        "coverage": (
                            len(candidate_items) / len(baseline_signals)
                            if baseline_signals else 0.0
                        ),
                        "min_n": 30 if opening else 50,
                        "min_days": 30 if opening else 40,
                    }
                )

    for strategy_id in ("S01", "S02", "S03"):
        for direction in ("LONG", "SHORT"):
            items = trade_groups.get((strategy_id, direction), [])
            baseline_min_n = 30 if strategy_id == "S02" else 50
            baseline_min_days = 30 if strategy_id == "S02" else 40
            add_value_spec(
                "STRATEGY_BASELINE",
                f"{strategy_id}_{direction}",
                items,
                lambda item: float(item["net_return"]),
                lambda item: True,
                min_n=baseline_min_n,
                min_days=baseline_min_days,
                target="mean_net_return_per_executed_trade",
            )

            aligned_preopen = (
                (lambda item: item.get("preopen_regime") == "BULL")
                if direction == "LONG"
                else (lambda item: item.get("preopen_regime") == "BEAR")
            )
            gap_aligned = (
                (lambda item: item.get("gap_regime") == "GAP_UP")
                if direction == "LONG"
                else (lambda item: item.get("gap_regime") == "GAP_DOWN")
            )
            regime_tests = {
                "S01": (
                    ("PREOPEN_ALIGNED", aligned_preopen),
                    ("VOL_NORMAL", lambda item: item.get("vol_regime") == "NORMAL"),
                ),
                "S02": (
                    ("GAP_ALIGNED", gap_aligned),
                    ("PREOPEN_ALIGNED", aligned_preopen),
                ),
                "S03": (
                    ("PREOPEN_NEUTRAL", lambda item: item.get("preopen_regime") == "NEUTRAL"),
                    ("VOL_NORMAL", lambda item: item.get("vol_regime") == "NORMAL"),
                ),
            }[strategy_id]
            for label, predicate in regime_tests:
                add_value_spec(
                    "REGIME_INCREMENT",
                    f"{strategy_id}_{direction}_{label}",
                    items,
                    lambda item, predicate=predicate: (
                        0.0 if predicate(item) else -float(item["net_return"])
                    ),
                    predicate,
                    min_n=25,
                    min_days=20,
                    target="paired_filtered_minus_baseline_return_per_opportunity",
                )

            for bucket in ("09:35-10:30", "10:30-12:00", "12:00-14:00", "14:00-15:55"):
                predicate = lambda item, bucket=bucket: item.get("time_bucket") == bucket
                add_value_spec(
                    "TIME_INCREMENT",
                    f"{strategy_id}_{direction}_{bucket}",
                    items,
                    lambda item, predicate=predicate: (
                        0.0 if predicate(item) else -float(item["net_return"])
                    ),
                    predicate,
                    min_n=25,
                    min_days=20,
                    target="paired_time_filter_minus_baseline_return_per_opportunity",
                )

            if strategy_id == "S01":
                interaction = lambda item, aligned_preopen=aligned_preopen: (
                    aligned_preopen(item) and item.get("vol_regime") == "NORMAL"
                )
                interaction_label = "PREOPEN_ALIGNED_X_VOL_NORMAL"
            elif strategy_id == "S02":
                interaction = lambda item, gap_aligned=gap_aligned: (
                    gap_aligned(item) and item.get("time_bucket") == "09:35-10:30"
                )
                interaction_label = "GAP_ALIGNED_X_OPENING_BUCKET"
            else:
                interaction = lambda item: (
                    item.get("preopen_regime") == "NEUTRAL"
                    and item.get("time_bucket") in {"10:30-12:00", "12:00-14:00"}
                )
                interaction_label = "PREOPEN_NEUTRAL_X_1030_1400"
            add_value_spec(
                "REGIME_TIME_INTERACTION",
                f"{strategy_id}_{direction}_{interaction_label}",
                items,
                lambda item, interaction=interaction: (
                    0.0 if interaction(item) else -float(item["net_return"])
                ),
                interaction,
                min_n=25,
                min_days=20,
                target="paired_interaction_filter_minus_baseline_return_per_opportunity",
            )

            for factor_index in range(6):
                predicate = lambda item, factor_index=factor_index: (
                    len(str(item.get("factor_filters", ""))) == 6
                    and str(item["factor_filters"])[factor_index] == "1"
                )
                add_value_spec(
                    "F001_F006_FILTER_INCREMENT",
                    f"{strategy_id}_{direction}_F{factor_index + 1:03d}",
                    items,
                    lambda item, predicate=predicate: (
                        0.0 if predicate(item) else -float(item["net_return"])
                    ),
                    predicate,
                    min_n=25,
                    min_days=20,
                    target="paired_factor_filter_minus_baseline_return_per_opportunity",
                )

    expected_sizes = {
        "CANDIDATE_SCREEN": 30,
        "STRATEGY_BASELINE": 6,
        "REGIME_INCREMENT": 12,
        "TIME_INCREMENT": 24,
        "REGIME_TIME_INTERACTION": 6,
        "F001_F006_FILTER_INCREMENT": 36,
    }
    results: list[dict] = []
    family_summaries: list[dict] = []
    for family, expected_size in expected_sizes.items():
        family_specs = [spec for spec in specs if spec["family"] == family]
        if len(family_specs) != expected_size:
            raise ValueError(f"INFERENCE_FAMILY_SIZE_MISMATCH:{family}")
        rng = random.Random(
            int(hashlib.sha256(f"{seed_key}|{family}".encode()).hexdigest()[:16], 16)
        )
        points = [spec["estimator"](study_days) for spec in family_specs]
        boot: list[list[float | None]] = [[] for _ in family_specs]
        if study_days:
            for _ in range(bootstrap_replicates):
                sampled_days = [
                    study_days[rng.randrange(len(study_days))] for _ in study_days
                ]
                for index, spec in enumerate(family_specs):
                    boot[index].append(spec["estimator"](sampled_days))
        standard_errors = [
            pstdev([value for value in values if value is not None])
            if len([value for value in values if value is not None]) > 1 else None
            for values in boot
        ]
        max_t_values = []
        for replicate in range(bootstrap_replicates):
            candidates = []
            for index, point in enumerate(points):
                value = boot[index][replicate] if boot[index] else None
                se = standard_errors[index]
                if point is not None and value is not None and se not in (None, 0):
                    candidates.append(abs((value - point) / se))
            if candidates:
                max_t_values.append(max(candidates))
        critical = _percentile(max_t_values, 0.95)
        raw_p_values = []
        for index, point in enumerate(points):
            valid = [value for value in boot[index] if value is not None]
            if point is None or not valid:
                raw_p_values.append(None)
            else:
                raw_p_values.append(
                    (1 + sum(abs(value - point) >= abs(point) for value in valid))
                    / (len(valid) + 1)
                )
        holm = _holm_adjust(raw_p_values, family_size=expected_size)
        for index, spec in enumerate(family_specs):
            point = points[index]
            se = standard_errors[index]
            valid_boot = [value for value in boot[index] if value is not None]
            enough = (
                spec["sample_count"] >= spec["min_n"]
                and spec["trading_days"] >= spec["min_days"]
            )
            results.append(
                {
                    "family": family,
                    "test_id": spec["test_id"],
                    "target": spec["target"],
                    "estimate": point,
                    "sample_count": spec["sample_count"],
                    "trading_days": spec["trading_days"],
                    "baseline_count": spec["baseline_count"],
                    "coverage": spec["coverage"],
                    "minimum_sample_count": spec["min_n"],
                    "minimum_trading_days": spec["min_days"],
                    "status": (
                        "INSUFFICIENT_SAMPLE"
                        if not enough else "ESTIMATED"
                        if point is not None else "NOT_ESTIMABLE"
                    ),
                    "cluster_ci_low": _percentile(valid_boot, 0.025),
                    "cluster_ci_high": _percentile(valid_boot, 0.975),
                    "simultaneous_ci_low": (
                        point - critical * se
                        if point is not None and critical is not None and se is not None
                        else None
                    ),
                    "simultaneous_ci_high": (
                        point + critical * se
                        if point is not None and critical is not None and se is not None
                        else None
                    ),
                    "raw_p_value": raw_p_values[index],
                    "holm_p_value": holm[index],
                    "bootstrap_replicates": len(valid_boot),
                }
            )
        family_summaries.append(
            {
                "family": family,
                "expected_tests": expected_size,
                "actual_tests": len(family_specs),
                "max_t_critical_95": critical,
                "estimable_tests": sum(point is not None for point in points),
                "bootstrap_replicates": bootstrap_replicates,
                "cluster_unit": "TRADING_DAY",
                "adjustment": "MAX_T_PLUS_HOLM",
            }
        )
    return {
        "results": results,
        "families": family_summaries,
        "study_days": len(study_days),
    }


def _holm_adjust(
    values: list[float | None], *, family_size: int | None = None
) -> list[float | None]:
    adjusted: list[float | None] = [None] * len(values)
    ordered = sorted(
        ((value, index) for index, value in enumerate(values) if value is not None)
    )
    running = 0.0
    count = family_size if family_size is not None else len(values)
    if count < len(ordered):
        raise ValueError("HOLM_FAMILY_SIZE_TOO_SMALL")
    for rank, (value, index) in enumerate(ordered):
        running = max(running, min(1.0, (count - rank) * value))
        adjusted[index] = running
    return adjusted


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


def compute_distribution_statistics(signals: list[dict], labels: list[dict]) -> list[dict]:
    """Return distribution details separately from the persisted statistics schema."""
    factor_by_signal = {item["signal_id"]: item["factor_value"] for item in signals}
    grouped: dict[tuple[int, str], list[float]] = defaultdict(list)
    for item in labels:
        horizon = int(item["horizon_minutes"])
        value = float(item["forward_return"])
        cohort = factor_by_signal[item["signal_id"]]
        grouped[(horizon, "ALL")].append(value)
        grouped[(horizon, cohort)].append(value)
    return [
        {
            "horizon_minutes": horizon,
            "cohort": cohort,
            **_summary(grouped.get((horizon, cohort), [])),
        }
        for horizon in (15, 30, 60)
        for cohort in ("ALL", "PASS", "FAIL")
    ]


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


def _time_bucket(time_text: str, minutes: int = 30) -> tuple[int, str]:
    hour, minute = (int(value) for value in time_text.split(":")[:2])
    anchor = 9 * 60 + 35
    offset = hour * 60 + minute - anchor
    if offset < 0:
        raise ValueError("signal time precedes the 09:35 RTH analysis anchor")
    bucket = offset // minutes
    start = anchor + bucket * minutes
    end = start + minutes
    label = f"[{start // 60:02d}:{start % 60:02d},{end // 60:02d}:{end % 60:02d})"
    return bucket, label


def compute_signal_redundancy(
    states_by_factor: dict[str, dict[str, str]],
) -> list[dict]:
    """Compare aligned binary factor states without using future returns."""
    rows: list[dict] = []
    for factor_a, factor_b in combinations(sorted(states_by_factor), 2):
        states_a = states_by_factor[factor_a]
        states_b = states_by_factor[factor_b]
        if set(states_a) != set(states_b):
            raise ValueError("factor signal ids are not aligned")
        pairs = [(states_a[key] == "PASS", states_b[key] == "PASS") for key in sorted(states_a)]
        if any(states_a[key] not in {"PASS", "FAIL"} for key in states_a):
            raise ValueError("factor states must be PASS or FAIL")
        if any(states_b[key] not in {"PASS", "FAIL"} for key in states_b):
            raise ValueError("factor states must be PASS or FAIL")
        n11 = sum(a and b for a, b in pairs)
        n10 = sum(a and not b for a, b in pairs)
        n01 = sum(not a and b for a, b in pairs)
        n00 = sum(not a and not b for a, b in pairs)
        denominator = ((n11 + n10) * (n01 + n00) * (n11 + n01) * (n10 + n00)) ** 0.5
        rows.append(
            {
                "factor_a": factor_a,
                "factor_b": factor_b,
                "n": len(pairs),
                "both_pass_n": n11,
                "agreement_rate": (n11 + n00) / len(pairs) if pairs else None,
                "phi": ((n11 * n00 - n10 * n01) / denominator) if denominator else None,
                "pass_jaccard": n11 / (n11 + n10 + n01) if n11 + n10 + n01 else None,
                "a_pass_given_b_pass": n11 / (n11 + n01) if n11 + n01 else None,
                "b_pass_given_a_pass": n11 / (n11 + n10) if n11 + n10 else None,
            }
        )
    return rows


def compute_train_analysis(
    signals: list[dict],
    labels: list[dict],
    *,
    seed_key: str,
    bootstrap_replicates: int = 5000,
    multiple_testing_family_size: int = 18,
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
        time_bucket_groups: dict[tuple[str, int], dict[str, object]] = {}
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
            bucket, bucket_label = _time_bucket(item["time"])
            stratum = time_bucket_groups.setdefault(
                (item["day"], bucket),
                {"day": item["day"], "bucket": bucket, "bucket_label": bucket_label,
                 "ALL": [], "PASS": [], "FAIL": []},
            )
            stratum["ALL"].append(value)
            stratum[cohort].append(value)

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

        time_bucket_matched: list[dict] = []
        for key in sorted(time_bucket_groups):
            groups = time_bucket_groups[key]
            difference_bps = _difference(groups["PASS"], groups["FAIL"])
            pass_n = len(groups["PASS"])
            fail_n = len(groups["FAIL"])
            match_weight = (
                pass_n * fail_n / (pass_n + fail_n) if pass_n and fail_n else 0.0
            )
            time_bucket_matched.append(
                {
                    "day": groups["day"],
                    "bucket": groups["bucket"],
                    "bucket_label": groups["bucket_label"],
                    "baseline": _summary(groups["ALL"]),
                    "pass": _summary(groups["PASS"]),
                    "fail": _summary(groups["FAIL"]),
                    "pass_fail_diff_bps": difference_bps,
                    "fixed_effect_weight": match_weight,
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
        matched_differences = [
            item["pass_fail_diff_bps"]
            for item in time_bucket_matched
            if item["pass_fail_diff_bps"] is not None
        ]
        matched_weight_total = sum(
            item["fixed_effect_weight"] for item in time_bucket_matched
        )
        fixed_effect_diff_bps = (
            sum(
                item["pass_fail_diff_bps"] * item["fixed_effect_weight"]
                for item in time_bucket_matched
                if item["pass_fail_diff_bps"] is not None
            )
            / matched_weight_total
            if matched_weight_total
            else None
        )
        tail_alpha = 0.05 / (2 * multiple_testing_family_size)
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
                "time_bucket_matched": time_bucket_matched,
                "same_day_time_bucket": {
                    "bucket_minutes": 30,
                    "anchor": "09:35 America/New_York",
                    "strata_total": len(time_bucket_matched),
                    "strata_matched": len(matched_differences),
                    "mean_stratum_diff_bps": mean(matched_differences) if matched_differences else None,
                    "median_stratum_diff_bps": median(matched_differences) if matched_differences else None,
                    "fixed_effect_diff_bps": fixed_effect_diff_bps,
                    "fixed_effect_weight_total": matched_weight_total,
                    "positive_strata": sum(value > 0 for value in matched_differences),
                    "negative_strata": sum(value < 0 for value in matched_differences),
                },
                "cluster_bootstrap": {
                    "unit": "trading_day",
                    "replicates_requested": bootstrap_replicates,
                    "replicates_valid": len(bootstrap_values),
                    "ci_low_bps": _percentile(bootstrap_values, 0.025),
                    "median_bps": _percentile(bootstrap_values, 0.5),
                    "ci_high_bps": _percentile(bootstrap_values, 0.975),
                    "multiple_testing_family_size": multiple_testing_family_size,
                    "bonferroni_simultaneous_confidence": 0.95,
                    "bonferroni_ci_low_bps": _percentile(bootstrap_values, tail_alpha),
                    "bonferroni_ci_high_bps": _percentile(bootstrap_values, 1 - tail_alpha),
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
                    "same-day time matching uses every fixed 30-minute bucket anchored at 09:35 ET",
                    "18 factor-horizon tests are reported with Bonferroni simultaneous intervals",
                    "TRAIN evidence cannot establish Validation or OOS support",
                ],
            }
        )
    return results
