from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd

from .contracts import BOOTSTRAP_ITERATIONS, BOOTSTRAP_SEED, COST_SCENARIOS_BPS, FactorSpec


def _seed(label: str) -> int:
    value = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)
    return (BOOTSTRAP_SEED + value) % (2**32)


def _cluster_summary(
    values: pd.Series,
    days: pd.Series,
    label: str,
    calendar_days: list[str] | np.ndarray | pd.Series | None = None,
) -> dict:
    """Estimate a per-observation mean with whole-day cluster resampling.

    The estimand is the equally weighted trade/event mean.  A bootstrap draw
    samples complete trading days and then recomputes that same ratio of total
    return to total observations; it never replaces the estimand with an
    equally weighted mean of daily means.
    """
    valid = pd.DataFrame({"value": values, "day": days}).dropna()
    observed_days = valid["day"].astype(str)
    if calendar_days is None:
        calendar = sorted(observed_days.unique())
    else:
        calendar = list(dict.fromkeys(str(item) for item in calendar_days))
    if valid.empty or not calendar:
        return {
            "mean": np.nan,
            "ci_low": np.nan,
            "ci_high": np.nan,
            "se": np.nan,
            "days": 0,
            "_cluster_days": np.asarray(calendar, dtype=object),
            "_cluster_sums": np.zeros(len(calendar), dtype=float),
            "_cluster_counts": np.zeros(len(calendar), dtype=float),
        }
    valid = valid.assign(day=observed_days)
    grouped = valid.groupby("day")["value"].agg(["sum", "count"]).reindex(calendar, fill_value=0)
    cluster_sums = grouped["sum"].to_numpy(dtype=float)
    cluster_counts = grouped["count"].to_numpy(dtype=float)
    estimate = float(cluster_sums.sum() / cluster_counts.sum())
    active_days = int((cluster_counts > 0).sum())
    if len(calendar) < 2:
        return {
            "mean": estimate,
            "ci_low": np.nan,
            "ci_high": np.nan,
            "se": np.nan,
            "days": active_days,
            "_cluster_days": np.asarray(calendar, dtype=object),
            "_cluster_sums": cluster_sums,
            "_cluster_counts": cluster_counts,
        }
    rng = np.random.default_rng(_seed(label))
    indices = rng.integers(0, len(calendar), size=(BOOTSTRAP_ITERATIONS, len(calendar)))
    denominators = cluster_counts[indices].sum(axis=1)
    numerators = cluster_sums[indices].sum(axis=1)
    samples = np.divide(
        numerators,
        denominators,
        out=np.full(BOOTSTRAP_ITERATIONS, np.nan, dtype=float),
        where=denominators > 0,
    )
    samples = samples[np.isfinite(samples)]
    return {
        "mean": estimate,
        "ci_low": float(np.quantile(samples, 0.025)) if len(samples) else np.nan,
        "ci_high": float(np.quantile(samples, 0.975)) if len(samples) else np.nan,
        "se": float(np.std(samples, ddof=1)) if len(samples) > 1 else np.nan,
        "days": active_days,
        "_cluster_days": np.asarray(calendar, dtype=object),
        "_cluster_sums": cluster_sums,
        "_cluster_counts": cluster_counts,
    }


def _holm(rows: list[dict], p_key: str = "raw_p_value") -> None:
    valid = [(index, row[p_key]) for index, row in enumerate(rows) if np.isfinite(row.get(p_key, np.nan))]
    ordered = sorted(valid, key=lambda item: item[1])
    adjusted = 0.0
    total = len(rows)
    for rank, (index, value) in enumerate(ordered):
        adjusted = max(adjusted, min(1.0, value * (total - rank)))
        rows[index]["holm_p_value"] = adjusted
    for row in rows:
        row.setdefault("holm_p_value", np.nan)


def _apply_family_adjustment(rows: list[dict], family_label: str = "family") -> None:
    eligible = [
        row for row in rows
        if np.isfinite(row.get("estimate", np.nan))
        and np.isfinite(row.get("se", np.nan))
        and row["se"] > 0
    ]
    if not eligible:
        for row in rows:
            row["simultaneous_ci_low"] = np.nan
            row["simultaneous_ci_high"] = np.nan
            row["raw_p_value"] = np.nan
            row["holm_p_value"] = np.nan
            row.pop("_cluster_days", None)
            row.pop("_cluster_sums", None)
            row.pop("_cluster_counts", None)
        return
    calendars = [tuple(str(item) for item in row["_cluster_days"]) for row in eligible]
    if any(calendar != calendars[0] for calendar in calendars[1:]):
        raise ValueError("FAMILY_CLUSTER_CALENDAR_MISMATCH")
    calendar_size = len(calendars[0])
    rng = np.random.default_rng(_seed("family-max-t-" + family_label))
    indices = rng.integers(0, calendar_size, size=(BOOTSTRAP_ITERATIONS, calendar_size))
    max_t = np.zeros(BOOTSTRAP_ITERATIONS)
    for row in eligible:
        sums = np.asarray(row["_cluster_sums"], dtype=float)
        counts = np.asarray(row["_cluster_counts"], dtype=float)
        centered_sums = sums - float(row["estimate"]) * counts
        denominators = counts[indices].sum(axis=1)
        sampled = np.divide(
            centered_sums[indices].sum(axis=1),
            denominators,
            out=np.full(BOOTSTRAP_ITERATIONS, np.nan, dtype=float),
            where=denominators > 0,
        )
        t_samples = np.abs(sampled / float(row["se"]))
        finite = np.isfinite(t_samples)
        max_t[finite] = np.maximum(max_t[finite], t_samples[finite])
        row["_null_abs_t"] = t_samples
    critical = float(np.quantile(max_t, 0.95))
    for row in rows:
        estimate = row.get("estimate", np.nan)
        se = row.get("se", np.nan)
        if np.isfinite(estimate) and np.isfinite(se) and se > 0:
            t_value = estimate / se
            null_abs_t = np.asarray(row.pop("_null_abs_t"), dtype=float)
            finite = null_abs_t[np.isfinite(null_abs_t)]
            row["raw_p_value"] = (
                float((1 + np.sum(finite >= abs(t_value))) / (len(finite) + 1))
                if len(finite)
                else np.nan
            )
            row["simultaneous_ci_low"] = estimate - critical * se
            row["simultaneous_ci_high"] = estimate + critical * se
        else:
            row["raw_p_value"] = np.nan
            row["simultaneous_ci_low"] = np.nan
            row["simultaneous_ci_high"] = np.nan
        row.pop("_cluster_days", None)
        row.pop("_cluster_sums", None)
        row.pop("_cluster_counts", None)
    _holm(rows)


def factor_results(events: pd.DataFrame, data: pd.DataFrame, specs: list[FactorSpec]) -> pd.DataFrame:
    spec_map = {item.factor_id: item for item in specs}
    rows: list[dict] = []
    train = data[data["is_train"]]
    calendar_days = list(train["session_date"].drop_duplicates().astype(str))
    for factor_id, factor_events in events.groupby("factor_id"):
        spec = spec_map[factor_id]
        for direction, directional_events in factor_events.groupby("direction"):
            direction_label = "LONG" if direction == 1 else "SHORT"
            if spec.direction == "REGIME":
                direction_label = "HIGH_OR_ACTIVE" if direction == 1 else "LOW_OR_CONTRACTION"
            for horizon, minutes in ((3, 15), (6, 30), (12, 60)):
                raw = directional_events[f"return_h{horizon}"].astype(float)
                valid = raw.notna()
                raw = raw[valid]
                days = directional_events.loc[valid, "session_date"]
                values = raw if spec.direction == "REGIME" else raw * int(direction)
                summary = _cluster_summary(
                    values,
                    days,
                    f"factor-{factor_id}-{direction}-{horizon}",
                    calendar_days,
                )
                baseline = float(train[f"return_h{horizon}"].mean())
                rows.append({
                    "factor_id": factor_id,
                    "category": spec.category,
                    "direction": direction_label,
                    "horizon_minutes": minutes,
                    "events": int(len(values)),
                    "trading_days": int(days.nunique()),
                    "raw_mean": float(raw.mean()) if len(raw) else np.nan,
                    "directional_mean": summary["mean"] if spec.direction != "REGIME" else np.nan,
                    "median": float(values.median()) if len(values) else np.nan,
                    "positive_rate": float((values > 0).mean()) if len(values) else np.nan,
                    "baseline_mean": baseline,
                    "increment": summary["mean"] - baseline if spec.direction != "REGIME" else float(raw.mean()) - baseline,
                    "cluster_ci_low": summary["ci_low"],
                    "cluster_ci_high": summary["ci_high"],
                    "estimate": summary["mean"],
                    "se": summary["se"],
                    "_cluster_days": summary["_cluster_days"],
                    "_cluster_sums": summary["_cluster_sums"],
                    "_cluster_counts": summary["_cluster_counts"],
                    "sample_status": "ELIGIBLE" if len(values) >= 50 and days.nunique() >= 40 else "INSUFFICIENT_SAMPLE",
                    "research_status": "EXPLORATORY_SAME_TRAIN_SAMPLE",
                })
    _apply_family_adjustment(rows, "factor-prediction")
    for row in rows:
        row.pop("estimate", None)
        row.pop("se", None)
    result = pd.DataFrame(rows)
    result["rank"] = np.nan
    mask = (result["horizon_minutes"] == 60) & result["directional_mean"].notna()
    result.loc[mask, "rank"] = result.loc[mask, "directional_mean"].rank(method="min", ascending=False)
    return result


def factor_correlation(matrix: pd.DataFrame, data: pd.DataFrame) -> pd.DataFrame:
    train = matrix.loc[data["is_train"].to_numpy()]
    rows: list[dict] = []
    columns = list(train.columns)
    for left_index, left in enumerate(columns):
        for right in columns[left_index + 1 :]:
            a = train[left].to_numpy(dtype=float)
            b = train[right].to_numpy(dtype=float)
            active_a = a != 0
            active_b = b != 0
            union = int((active_a | active_b).sum())
            joint = int((active_a & active_b).sum())
            signed_corr = float(np.corrcoef(a, b)[0, 1]) if a.std() > 0 and b.std() > 0 else np.nan
            phi = float(np.corrcoef(active_a.astype(float), active_b.astype(float))[0, 1]) if active_a.std() > 0 and active_b.std() > 0 else np.nan
            rows.append({
                "factor_a": left,
                "factor_b": right,
                "signed_correlation": signed_corr,
                "activation_phi": phi,
                "joint_events": joint,
                "jaccard": joint / union if union else np.nan,
                "duplicate_flag": bool(np.isfinite(phi) and abs(phi) >= 0.80),
            })
    return pd.DataFrame(rows)


def _max_drawdown(returns: pd.Series) -> float:
    equity = (1.0 + returns.fillna(0.0)).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    return float(drawdown.min()) if len(drawdown) else np.nan


def strategy_results(trades: pd.DataFrame, calendar_days: list[str] | pd.Series | np.ndarray | None = None) -> pd.DataFrame:
    rows: list[dict] = []
    if trades.empty:
        return pd.DataFrame()
    groups: list[tuple[tuple[str, str], pd.DataFrame]] = []
    for variant, group in trades.groupby("variant_id"):
        groups.append(((variant, "ALL"), group))
        groups.extend([((variant, direction), sub) for direction, sub in group.groupby("direction")])
    for (variant, direction), group in groups:
        returns = group["net_return"].astype(float)
        gains = returns[returns > 0].sum()
        losses = -returns[returns < 0].sum()
        summary = _cluster_summary(
            returns,
            group["session_date"],
            f"strategy-{variant}-{direction}",
            calendar_days,
        )
        monthly = group.assign(month=group["session_date"].str[:7]).groupby("month")["net_return"].sum()
        positive_total = monthly[monthly > 0].sum()
        max_month_share = float(monthly[monthly > 0].max() / positive_total) if positive_total > 0 else np.nan
        minimum_trades = 30 if variant.startswith("S02") else 50
        minimum_days = 30 if variant.startswith("S02") else 40
        row = {
            "variant_id": variant,
            "strategy_id": variant[:3],
            "direction": direction,
            "trades": len(group),
            "trading_days": int(group["session_date"].nunique()),
            "gross_mean": float(group["gross_return"].mean()),
            "net_mean": float(returns.mean()),
            "median": float(returns.median()),
            "win_rate": float((returns > 0).mean()),
            "profit_factor": float(gains / losses) if losses > 0 else np.nan,
            "max_drawdown": _max_drawdown(returns),
            "mfe_mean": float(group["mfe"].mean()),
            "mae_mean": float(group["mae"].mean()),
            "cluster_ci_low": summary["ci_low"],
            "cluster_ci_high": summary["ci_high"],
            "ambiguous_paths": int(group["ambiguous_path"].sum()),
            "path_uncertain_exits": int(group["path_uncertain"].sum()),
            "positive_months": int((monthly > 0).sum()),
            "max_positive_month_share": max_month_share,
            "sample_status": "ELIGIBLE" if len(group) >= minimum_trades and group["session_date"].nunique() >= minimum_days else "INSUFFICIENT_SAMPLE",
            "estimate": summary["mean"],
            "se": summary["se"],
            "_cluster_days": summary["_cluster_days"],
            "_cluster_sums": summary["_cluster_sums"],
            "_cluster_counts": summary["_cluster_counts"],
        }
        rows.append(row)
    _apply_family_adjustment(rows, "strategy-baseline-and-filter")
    for row in rows:
        qualifies = (
            row["sample_status"] == "ELIGIBLE"
            and row["simultaneous_ci_low"] > 0
            and row["profit_factor"] > 1.10
            and row["positive_months"] >= 6
            and row["max_positive_month_share"] <= 0.40
        )
        row["candidate_status"] = "TRAIN_CANDIDATE" if qualifies else "NO_EVIDENCE"
        row["research_status"] = "EXPLORATORY_SAME_TRAIN_SAMPLE"
        row.pop("estimate", None)
        row.pop("se", None)
    return pd.DataFrame(rows)


def regime_time_results(trades: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    dimensions = ["premarket_trend", "premarket_vol", "dynamic_trend", "f012_state", "dynamic_gap", "time_bucket"]
    rows: list[dict] = []
    for variant, group in trades.groupby("variant_id"):
        for dimension in dimensions:
            for value, subset in group.groupby(dimension):
                rows.append({
                    "entity_type": "STRATEGY",
                    "entity_id": variant,
                    "variant_id": variant,
                    "factor_id": "",
                    "direction": "ALL",
                    "horizon_minutes": "",
                    "dimension": dimension,
                    "value": value,
                    "trades": len(subset),
                    "events": "",
                    "trading_days": int(subset["session_date"].nunique()),
                    "net_mean": float(subset["net_return"].mean()),
                    "directional_mean": float(subset["net_return"].mean()),
                    "profit_factor": float(subset.loc[subset["net_return"] > 0, "net_return"].sum() / -subset.loc[subset["net_return"] < 0, "net_return"].sum()) if (subset["net_return"] < 0).any() else np.nan,
                    "status": "DESCRIPTIVE_ONLY" if len(subset) < 25 or subset["session_date"].nunique() < 20 else "EXPLORATORY_ELIGIBLE",
                })
    interaction_masks = {
        "S01_BASE": (
            ((trades["direction"] == "LONG") & (trades["premarket_trend"] == "BULL"))
            | ((trades["direction"] == "SHORT") & (trades["premarket_trend"] == "BEAR"))
        ) & (trades["premarket_vol"] == "NORMAL"),
        "S02_BASE": (
            ((trades["direction"] == "LONG") & (trades["dynamic_gap"] == "GAP_UP"))
            | ((trades["direction"] == "SHORT") & (trades["dynamic_gap"] == "GAP_DOWN"))
        ) & (trades["time_bucket"] == "09:35-10:30"),
        "S03_BASE": (trades["premarket_trend"] == "NEUTRAL") & trades["time_bucket"].isin(["10:30-12:00", "12:00-14:00"]),
    }
    interaction_names = {
        "S01_BASE": "TREND_ALIGNED_X_NORMAL_VOL",
        "S02_BASE": "GAP_ALIGNED_X_OPENING_BUCKET",
        "S03_BASE": "PREMARKET_NEUTRAL_X_MIDDAY",
    }
    for variant, mask in interaction_masks.items():
        subset = trades[(trades["variant_id"] == variant) & mask]
        if subset.empty:
            continue
        rows.append({
            "entity_type": "STRATEGY", "entity_id": variant, "variant_id": variant,
            "factor_id": "", "direction": "ALL", "horizon_minutes": "",
            "dimension": "PRE_REGISTERED_INTERACTION", "value": interaction_names[variant],
            "trades": len(subset), "events": "", "trading_days": int(subset["session_date"].nunique()),
            "net_mean": float(subset["net_return"].mean()), "directional_mean": float(subset["net_return"].mean()),
            "profit_factor": float(subset.loc[subset["net_return"] > 0, "net_return"].sum() / -subset.loc[subset["net_return"] < 0, "net_return"].sum()) if (subset["net_return"] < 0).any() else np.nan,
            "status": "DESCRIPTIVE_ONLY" if len(subset) < 25 or subset["session_date"].nunique() < 20 else "EXPLORATORY_ELIGIBLE",
        })
    factor_dimensions = ["premarket_trend", "dynamic_trend", "f012_state", "time_bucket"]
    eligible_events = events[events["return_h12"].notna()].copy()
    eligible_events["directional_h60"] = eligible_events["return_h12"] * eligible_events["direction"]
    for (factor_id, direction), group in eligible_events.groupby(["factor_id", "direction"]):
        direction_name = "LONG" if direction == 1 else "SHORT"
        for dimension in factor_dimensions:
            for value, subset in group.groupby(dimension):
                rows.append({
                    "entity_type": "FACTOR", "entity_id": factor_id, "variant_id": "",
                    "factor_id": factor_id, "direction": direction_name, "horizon_minutes": 60,
                    "dimension": dimension, "value": value, "trades": "", "events": len(subset),
                    "trading_days": int(subset["session_date"].nunique()), "net_mean": np.nan,
                    "directional_mean": float(subset["directional_h60"].mean()), "profit_factor": np.nan,
                    "status": "DESCRIPTIVE_ONLY" if len(subset) < 25 or subset["session_date"].nunique() < 20 else "EXPLORATORY_ELIGIBLE",
                })
    return pd.DataFrame(rows)


def robustness_results(trades: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    for variant, group in trades.groupby("variant_id"):
        for cost in COST_SCENARIOS_BPS:
            values = group["gross_return"] - cost / 10_000.0
            rows.append({
                "variant_id": variant,
                "cost_round_trip_bps": cost,
                "trades": len(group),
                "net_mean": float(values.mean()),
                "win_rate": float((values > 0).mean()),
                "profit_factor": float(values[values > 0].sum() / -values[values < 0].sum()) if (values < 0).any() else np.nan,
            })
    return pd.DataFrame(rows)


def test_registry(factor_rows: pd.DataFrame, strategy_rows: pd.DataFrame, regime_rows: pd.DataFrame) -> pd.DataFrame:
    records = [
        {"family": "FACTOR_PREDICTION", "actual_tests": len(factor_rows), "cluster_unit": "TRADING_DAY", "multiplicity": "COMMON_DAY_MAX_ABS_T_AND_FULL_FAMILY_HOLM", "attempt_version": "PHASE3_V2"},
        {"family": "STRATEGY_BASELINE_AND_FILTER", "actual_tests": len(strategy_rows), "cluster_unit": "TRADING_DAY", "multiplicity": "COMMON_DAY_MAX_ABS_T_AND_FULL_FAMILY_HOLM", "attempt_version": "PHASE3_V2"},
        {"family": "REGIME_TIME_DIAGNOSTIC", "actual_tests": len(regime_rows), "cluster_unit": "TRADING_DAY", "multiplicity": "DESCRIPTIVE_PRE_REGISTERED_DIMENSIONS", "attempt_version": "PHASE3_V2"},
    ]
    return pd.DataFrame(records)
