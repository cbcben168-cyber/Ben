from __future__ import annotations

import hashlib
import math

import numpy as np
import pandas as pd

from .contracts import BOOTSTRAP_ITERATIONS, BOOTSTRAP_SEED, COST_SCENARIOS_BPS, FactorSpec


def _seed(label: str) -> int:
    value = int(hashlib.sha256(label.encode("utf-8")).hexdigest()[:8], 16)
    return (BOOTSTRAP_SEED + value) % (2**32)


def _cluster_summary(values: pd.Series, days: pd.Series, label: str) -> dict:
    valid = pd.DataFrame({"value": values, "day": days}).dropna()
    if valid.empty:
        return {"mean": np.nan, "ci_low": np.nan, "ci_high": np.nan, "se": np.nan, "days": 0}
    daily = valid.groupby("day")["value"].mean().to_numpy(dtype=float)
    estimate = float(valid["value"].mean())
    if len(daily) < 2:
        return {"mean": estimate, "ci_low": np.nan, "ci_high": np.nan, "se": np.nan, "days": len(daily)}
    rng = np.random.default_rng(_seed(label))
    samples = daily[rng.integers(0, len(daily), size=(BOOTSTRAP_ITERATIONS, len(daily)))].mean(axis=1)
    return {
        "mean": estimate,
        "ci_low": float(np.quantile(samples, 0.025)),
        "ci_high": float(np.quantile(samples, 0.975)),
        "se": float(np.std(samples, ddof=1)),
        "days": len(daily),
    }


def _holm(rows: list[dict], p_key: str = "raw_p_value") -> None:
    valid = [(index, row[p_key]) for index, row in enumerate(rows) if np.isfinite(row.get(p_key, np.nan))]
    ordered = sorted(valid, key=lambda item: item[1])
    adjusted = 0.0
    total = len(ordered)
    for rank, (index, value) in enumerate(ordered):
        adjusted = max(adjusted, min(1.0, value * (total - rank)))
        rows[index]["holm_p_value"] = adjusted
    for row in rows:
        row.setdefault("holm_p_value", np.nan)


def _apply_family_adjustment(rows: list[dict]) -> None:
    eligible = [row for row in rows if np.isfinite(row.get("estimate", np.nan)) and np.isfinite(row.get("se", np.nan)) and row["se"] > 0]
    if not eligible:
        for row in rows:
            row["simultaneous_ci_low"] = np.nan
            row["simultaneous_ci_high"] = np.nan
            row["raw_p_value"] = np.nan
            row["holm_p_value"] = np.nan
        return
    rng = np.random.default_rng(_seed("family-max-t-" + str(len(eligible))))
    max_t = np.zeros(BOOTSTRAP_ITERATIONS)
    for row in eligible:
        daily = np.asarray(row.pop("_daily"), dtype=float)
        centered = daily - daily.mean()
        if len(daily) < 2 or centered.std(ddof=1) == 0:
            continue
        sampled = centered[rng.integers(0, len(centered), size=(BOOTSTRAP_ITERATIONS, len(centered)))].mean(axis=1)
        scale = centered.std(ddof=1) / math.sqrt(len(centered))
        max_t = np.maximum(max_t, np.abs(sampled / scale))
    critical = float(np.quantile(max_t, 0.95))
    for row in rows:
        estimate = row.get("estimate", np.nan)
        se = row.get("se", np.nan)
        row.pop("_daily", None)
        if np.isfinite(estimate) and np.isfinite(se) and se > 0:
            t_value = estimate / se
            row["raw_p_value"] = math.erfc(abs(t_value) / math.sqrt(2.0))
            row["simultaneous_ci_low"] = estimate - critical * se
            row["simultaneous_ci_high"] = estimate + critical * se
        else:
            row["raw_p_value"] = np.nan
            row["simultaneous_ci_low"] = np.nan
            row["simultaneous_ci_high"] = np.nan
    _holm(rows)


def factor_results(events: pd.DataFrame, data: pd.DataFrame, specs: list[FactorSpec]) -> pd.DataFrame:
    spec_map = {item.factor_id: item for item in specs}
    rows: list[dict] = []
    train = data[data["is_train"]]
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
                summary = _cluster_summary(values, days, f"factor-{factor_id}-{direction}-{horizon}")
                daily = pd.DataFrame({"value": values, "day": days}).groupby("day")["value"].mean().to_numpy()
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
                    "_daily": daily,
                    "sample_status": "ELIGIBLE" if len(values) >= 50 and days.nunique() >= 40 else "INSUFFICIENT_SAMPLE",
                    "research_status": "EXPLORATORY_SAME_TRAIN_SAMPLE",
                })
    _apply_family_adjustment(rows)
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


def strategy_results(trades: pd.DataFrame) -> pd.DataFrame:
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
        summary = _cluster_summary(returns, group["session_date"], f"strategy-{variant}-{direction}")
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
            "_daily": group.groupby("session_date")["net_return"].mean().to_numpy(),
        }
        rows.append(row)
    _apply_family_adjustment(rows)
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
        {"family": "FACTOR_PREDICTION", "actual_tests": len(factor_rows), "cluster_unit": "TRADING_DAY", "multiplicity": "MAX_ABS_T_AND_HOLM", "attempt_version": "PHASE3_V1"},
        {"family": "STRATEGY_BASELINE_AND_FILTER", "actual_tests": len(strategy_rows), "cluster_unit": "TRADING_DAY", "multiplicity": "MAX_ABS_T_AND_HOLM", "attempt_version": "PHASE3_V1"},
        {"family": "REGIME_TIME_DIAGNOSTIC", "actual_tests": len(regime_rows), "cluster_unit": "TRADING_DAY", "multiplicity": "DESCRIPTIVE_PRE_REGISTERED_DIMENSIONS", "attempt_version": "PHASE3_V1"},
    ]
    return pd.DataFrame(records)
