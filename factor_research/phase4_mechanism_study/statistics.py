from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from .contracts import (
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    FAMILY,
    PRIMARY_COST,
    ROBUSTNESS_COST,
    SENSITIVITY_COST,
    TRAIN_SESSIONS,
    Phase4ContractError,
)


@dataclass(frozen=True)
class StatisticsResult:
    summary: pd.DataFrame
    holm_family_size: int
    common_indices_sha256: str
    candidate_count: int
    gate_status: str


def _common_bootstrap_indices(day_count: int, iterations: int) -> np.ndarray:
    label_hash = int.from_bytes(hashlib.sha256(b"P4_PRIMARY_V1").digest()[:8], "big")
    seed = (BOOTSTRAP_SEED + label_hash) % (2**63 - 1)
    return np.random.default_rng(seed).integers(0, day_count, size=(iterations, day_count))


def _holm(p_values: Sequence[float]) -> np.ndarray:
    p = np.asarray(p_values, dtype=float)
    order = np.argsort(p, kind="stable")
    adjusted = np.empty_like(p)
    running = 0.0
    family_size = len(p)
    for rank, index in enumerate(order):
        running = max(running, min(1.0, (family_size - rank) * p[index]))
        adjusted[index] = running
    return adjusted


def _validate_inputs(trades: pd.DataFrame, calendar: Iterable[str], expected_days: int) -> tuple[pd.DataFrame, list[str]]:
    required = {"hypothesis_id", "session_date", "gross_return"}
    if not required.issubset(trades.columns):
        raise Phase4ContractError("STATISTICS_COLUMNS_MISSING")
    frame = trades.loc[:, sorted(required)].copy()
    days = [str(day) for day in calendar]
    if len(days) != expected_days or len(days) != len(set(days)) or days != sorted(days):
        raise Phase4ContractError("INVALID_COMMON_DAY_INDEX")
    if set(frame["hypothesis_id"]).difference(FAMILY):
        raise Phase4ContractError("INCOMPLETE_OR_UNREGISTERED_FAMILY")
    frame["session_date"] = frame["session_date"].astype(str)
    if not set(frame["session_date"]).issubset(days):
        raise Phase4ContractError("TRADE_OUTSIDE_COMMON_DAY_INDEX")
    frame["gross_return"] = pd.to_numeric(frame["gross_return"], errors="coerce")
    if not np.isfinite(frame["gross_return"].to_numpy(dtype=float)).all():
        raise Phase4ContractError("NONFINITE_STATISTICAL_INPUT")
    return frame, days


def evaluate_family(
    trades: pd.DataFrame,
    calendar: Iterable[str],
    *,
    expected_days: int = TRAIN_SESSIONS,
    iterations: int = BOOTSTRAP_ITERATIONS,
) -> StatisticsResult:
    if iterations != BOOTSTRAP_ITERATIONS:
        raise Phase4ContractError("BOOTSTRAP_ITERATIONS_NOT_FROZEN")
    frame, days = _validate_inputs(trades, calendar, expected_days)
    indices = _common_bootstrap_indices(len(days), iterations)
    index_hash = hashlib.sha256(indices.tobytes()).hexdigest()
    day_lookup = {day: idx for idx, day in enumerate(days)}
    rows: list[dict[str, float | int | str | bool]] = []
    centered_t: list[np.ndarray] = []

    for hypothesis_id in FAMILY:
        selected = frame.loc[frame["hypothesis_id"] == hypothesis_id].copy()
        selected["net_4bp"] = selected["gross_return"] - PRIMARY_COST
        selected["net_2bp"] = selected["gross_return"] - SENSITIVITY_COST
        selected["net_6bp"] = selected["gross_return"] - ROBUSTNESS_COST
        day_sums = np.zeros(len(days), dtype=float)
        day_counts = np.zeros(len(days), dtype=int)
        for day, group in selected.groupby("session_date", sort=False):
            position = day_lookup[day]
            day_sums[position] = float(group["net_4bp"].sum())
            day_counts[position] = len(group)
        sampled_sums = day_sums[indices].sum(axis=1)
        sampled_counts = day_counts[indices].sum(axis=1)
        bootstrap_means = np.divide(
            sampled_sums,
            sampled_counts,
            out=np.full(iterations, np.nan),
            where=sampled_counts > 0,
        )
        trade_count = len(selected)
        trading_days = int((day_counts > 0).sum())
        if trade_count:
            mean_4bp = float(selected["net_4bp"].mean())
            mean_2bp = float(selected["net_2bp"].mean())
            mean_6bp = float(selected["net_6bp"].mean())
            standard_error = float(np.nanstd(bootstrap_means, ddof=1))
        else:
            mean_4bp = mean_2bp = mean_6bp = float("nan")
            standard_error = float("nan")
        if np.isfinite(standard_error) and standard_error > 0:
            observed_t = mean_4bp / standard_error
            draws = (bootstrap_means - mean_4bp) / standard_error
            p_value = float((1 + np.sum(np.abs(draws[np.isfinite(draws)]) >= abs(observed_t))) / (1 + np.isfinite(draws).sum()))
        else:
            observed_t = float("nan")
            draws = np.full(iterations, np.nan)
            p_value = 1.0
        centered_t.append(draws)

        positives = selected.loc[selected["net_4bp"] > 0, "net_4bp"].sum()
        negatives = -selected.loc[selected["net_4bp"] < 0, "net_4bp"].sum()
        profit_factor = float(positives / negatives) if negatives > 0 else float("nan")
        if trade_count:
            selected["month"] = pd.to_datetime(selected["session_date"]).dt.to_period("M").astype(str)
            monthly = selected.groupby("month", sort=True)["net_4bp"].sum()
            positive_monthly = monthly.loc[monthly > 0]
            positive_months = int(len(positive_monthly))
            total_positive_monthly = float(positive_monthly.sum())
            concentration = float(positive_monthly.max() / total_positive_monthly) if total_positive_monthly > 0 else float("nan")
        else:
            positive_months = 0
            concentration = float("nan")
        rows.append(
            {
                "hypothesis_id": hypothesis_id,
                "trade_count": trade_count,
                "trading_days": trading_days,
                "mean_net_return_2bp": mean_2bp,
                "mean_net_return_4bp": mean_4bp,
                "mean_net_return_6bp": mean_6bp,
                "standard_error": standard_error,
                "observed_t": observed_t,
                "p_value_raw": p_value,
                "profit_factor": profit_factor,
                "positive_months": positive_months,
                "max_positive_month_share": concentration,
            }
        )

    summary = pd.DataFrame(rows)
    summary["p_value_holm"] = _holm(summary["p_value_raw"].to_numpy())
    t_matrix = np.column_stack(centered_t)
    finite_matrix = np.where(np.isfinite(t_matrix), np.abs(t_matrix), 0.0)
    critical = float(np.quantile(finite_matrix.max(axis=1), 0.95, method="higher"))
    summary["simultaneous_ci_low"] = summary["mean_net_return_4bp"] - critical * summary["standard_error"]
    summary["simultaneous_ci_high"] = summary["mean_net_return_4bp"] + critical * summary["standard_error"]
    summary["candidate"] = (
        (summary["trade_count"] >= 50)
        & (summary["trading_days"] >= 40)
        & (summary["p_value_holm"] < 0.05)
        & (summary["simultaneous_ci_low"] > 0)
        & np.isfinite(summary["profit_factor"])
        & (summary["profit_factor"] > 1.10)
        & (summary["positive_months"] >= 6)
        & (summary["max_positive_month_share"] <= 0.40)
        & (summary["mean_net_return_6bp"] > 0)
    )
    candidate_count = int(summary["candidate"].sum())
    return StatisticsResult(
        summary=summary,
        holm_family_size=len(FAMILY),
        common_indices_sha256=index_hash,
        candidate_count=candidate_count,
        gate_status="PASS_ALLOW_ZERO_CANDIDATES",
    )
