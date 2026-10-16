from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

EVIDENCE_LABEL = "SYNTHETIC_DEMO"
TRAIN_EVIDENCE_LABEL = "EXPLORATORY_SCREEN_ONLY"
PRIMARY_HORIZON_BARS = 6
REQUIRED_COLUMNS = (
    "timestamp_utc",
    "bar_available_at_utc",
    "session_date",
    "open",
    "high",
    "low",
    "close",
    "pit_status",
    "session_complete",
)
PRICE_COLUMNS = ("open", "high", "low", "close")


class ScoutBlocked(ValueError):
    """Fail-closed data, specification, or PIT qualification failure."""


@dataclass
class RunCounters:
    data_reads: int = 0
    feature_passes: int = 0
    forward_passes: int = 0


@dataclass(frozen=True)
class FactorDefinition:
    factor_id: str
    name: str
    target_type: str
    anchor_time_et: str
    value: Callable[[pd.Series], float]
    exposed: Callable[[float], bool]
    direction: Callable[[float], int]


def _finite(value: object) -> float:
    result = float(value)
    return result if np.isfinite(result) else np.nan


FACTORS = (
    FactorDefinition(
        "F01", "Opening Drive Persistence", "DIRECTION", "10:00",
        lambda row: _finite((row["close"] - row["session_open"]) / row["daily_atr20"]),
        lambda value: abs(value) >= 0.25,
        lambda value: 1 if value > 0 else -1,
    ),
    FactorDefinition(
        "F02", "Opening Volatility Persistence", "VOLATILITY", "10:00",
        lambda row: _finite(row["daily_range_so_far"] / row["daily_atr20"]),
        lambda value: value >= 0.35,
        lambda value: 1,
    ),
    FactorDefinition(
        "F03", "Morning Directional Efficiency", "DIRECTION", "10:30",
        lambda row: _finite(row["directional_efficiency"]),
        lambda value: abs(value) >= 0.60,
        lambda value: 1 if value > 0 else -1,
    ),
    FactorDefinition(
        "F04", "Previous-Day Close Location", "STATE", "09:35",
        lambda row: _finite(row["prev_close_location"]),
        lambda value: value <= 0.25 or value >= 0.75,
        lambda value: 1 if value >= 0.75 else -1,
    ),
    FactorDefinition(
        "F05", "Previous-Day Range Regime", "STATE", "09:35",
        lambda row: _finite(row["prev_day_range"] / row["prev_daily_atr20"]),
        lambda value: value <= 0.75 or value >= 1.25,
        lambda value: 1 if value >= 1.25 else -1,
    ),
    FactorDefinition(
        "F06", "Midday Range Position", "DIRECTION", "13:00",
        lambda row: _finite(row["range_position"]),
        lambda value: value <= 0.25 or value >= 0.75,
        lambda value: 1 if value >= 0.75 else -1,
    ),
)


def load_registry(path: Path) -> pd.DataFrame:
    registry = pd.read_csv(path, dtype=str, keep_default_na=False)
    if tuple(registry["factor_id"]) != tuple(f.factor_id for f in FACTORS):
        raise ScoutBlocked("BLOCKED_SPEC:FACTOR_REGISTRY_ORDER_OR_MEMBERSHIP")
    if registry[["formula_source_path", "formula_source_sha256"]].eq("").any().any():
        raise ScoutBlocked("BLOCKED_SPEC:MISSING_FROZEN_SOURCE_IDENTITY")
    return registry


def qualify_ohlc(
    raw: pd.DataFrame,
    counters: RunCounters | None = None,
    *,
    session_close_by_date: dict[str, str] | None = None,
    allowed_pit_statuses: frozenset[str] = frozenset({"PIT_VERIFIED"}),
) -> pd.DataFrame:
    if counters is not None:
        counters.data_reads += 1
    missing = sorted(set(REQUIRED_COLUMNS) - set(raw.columns))
    if missing:
        raise ScoutBlocked(f"BLOCKED_DATA:MISSING_COLUMNS:{','.join(missing)}")
    if raw.empty:
        raise ScoutBlocked("BLOCKED_DATA:EMPTY_OHLC")
    frame = raw.loc[:, REQUIRED_COLUMNS].copy()
    for column in ("timestamp_utc", "bar_available_at_utc"):
        frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
        if frame[column].isna().any():
            raise ScoutBlocked(f"BLOCKED_DATA:INVALID_{column.upper()}")
    if not frame["timestamp_utc"].is_monotonic_increasing:
        raise ScoutBlocked("BLOCKED_DATA:UNSORTED_TIMESTAMPS")
    if frame["timestamp_utc"].duplicated().any():
        raise ScoutBlocked("BLOCKED_DATA:DUPLICATE_TIMESTAMPS")
    if (frame["bar_available_at_utc"] > frame["timestamp_utc"]).any():
        raise ScoutBlocked("BLOCKED_PIT:BAR_AVAILABLE_AFTER_BAR_END")
    if not frame["pit_status"].isin(allowed_pit_statuses).all():
        raise ScoutBlocked("BLOCKED_PIT:UNQUALIFIED_PRICE_BASIS")
    prices = frame.loc[:, PRICE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(prices.to_numpy(dtype=float)).all() or (prices <= 0).any().any():
        raise ScoutBlocked("BLOCKED_DATA:NONFINITE_OR_NONPOSITIVE_PRICE")
    frame.loc[:, PRICE_COLUMNS] = prices
    if (frame["high"] < frame[["open", "close"]].max(axis=1)).any():
        raise ScoutBlocked("BLOCKED_DATA:HIGH_BELOW_OPEN_OR_CLOSE")
    if (frame["low"] > frame[["open", "close"]].min(axis=1)).any():
        raise ScoutBlocked("BLOCKED_DATA:LOW_ABOVE_OPEN_OR_CLOSE")
    local = frame["timestamp_utc"].dt.tz_convert("America/New_York")
    if not frame["session_date"].eq(local.dt.strftime("%Y-%m-%d")).all():
        raise ScoutBlocked("BLOCKED_DATA:SESSION_DATE_MISMATCH")
    frame["time_et"] = local.dt.strftime("%H:%M")
    session_order = frame["session_date"].drop_duplicates().tolist()
    for position, session_date in enumerate(session_order):
        day = frame.loc[frame["session_date"].eq(session_date)]
        declared_complete = bool(day["session_complete"].all())
        close_time = (session_close_by_date or {}).get(session_date, "16:00")
        expected_bars = 42 if close_time == "13:00" else 78
        if close_time not in {"13:00", "16:00"}:
            raise ScoutBlocked("BLOCKED_DATA:UNEXPECTED_SESSION_CLOSE")
        grid_complete = (
            len(day) == expected_bars
            and day.iloc[0]["time_et"] == "09:35"
            and day.iloc[-1]["time_et"] == close_time
            and day["timestamp_utc"].diff().dropna().eq(pd.Timedelta(minutes=5)).all()
        )
        if declared_complete != grid_complete:
            raise ScoutBlocked("BLOCKED_DATA:SESSION_COMPLETENESS_MISMATCH")
        if not declared_complete and position != len(session_order) - 1:
            raise ScoutBlocked("BLOCKED_DATA:INCOMPLETE_HISTORICAL_SESSION")
    return frame.reset_index(drop=True)


def compute_shared_features(bars: pd.DataFrame, counters: RunCounters | None = None) -> pd.DataFrame:
    if counters is not None:
        counters.feature_passes += 1
    frame = bars.copy()
    grouped = frame.groupby("session_date", sort=False)
    frame["bar_in_session"] = grouped.cumcount()
    frame["global_pos"] = np.arange(len(frame), dtype=int)
    frame["session_open"] = grouped["open"].transform("first")
    frame["session_high"] = grouped["high"].cummax()
    frame["session_low"] = grouped["low"].cummin()
    frame["daily_range_so_far"] = frame["session_high"] - frame["session_low"]
    frame["range_position"] = (
        (frame["close"] - frame["session_low"])
        / frame["daily_range_so_far"].replace(0.0, np.nan)
    )
    previous_close = grouped["close"].shift(1)
    first_path = (frame["close"] - frame["open"]).abs()
    later_path = (frame["close"] - previous_close).abs()
    frame["path_increment"] = later_path.where(frame["bar_in_session"].ne(0), first_path)
    path_length = frame["path_increment"].groupby(frame["session_date"], sort=False).cumsum()
    frame["directional_efficiency"] = (
        (frame["close"] - frame["session_open"]) / path_length.replace(0.0, np.nan)
    )
    first_return = np.log(frame["close"] / frame["open"])
    later_return = np.log(frame["close"] / previous_close)
    frame["intraday_log_return"] = later_return.where(frame["bar_in_session"].ne(0), first_return)
    daily = grouped.agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last"),
        is_complete=("session_complete", "all"),
    )
    daily["daily_range"] = daily["high"] - daily["low"]
    daily["close_location"] = (
        (daily["close"] - daily["low"]) / daily["daily_range"].replace(0.0, np.nan)
    )
    daily["previous_close"] = daily["close"].shift(1)
    daily["daily_true_range"] = pd.concat(
        [
            daily["daily_range"],
            (daily["high"] - daily["previous_close"]).abs(),
            (daily["low"] - daily["previous_close"]).abs(),
        ], axis=1,
    ).max(axis=1, skipna=False)
    daily.loc[~daily["is_complete"], ["daily_range", "close_location", "daily_true_range"]] = np.nan
    daily["daily_atr20"] = daily["daily_true_range"].shift(1).rolling(20, min_periods=20).mean()
    daily["prev_day_range"] = daily["daily_range"].shift(1)
    daily["prev_close_location"] = daily["close_location"].shift(1)
    daily["prev_daily_atr20"] = daily["daily_atr20"].shift(1)
    for column in ("daily_atr20", "prev_day_range", "prev_close_location", "prev_daily_atr20"):
        frame[column] = frame["session_date"].map(daily[column])
    return frame


def compute_forward_responses(features: pd.DataFrame, counters: RunCounters | None = None) -> pd.DataFrame:
    if counters is not None:
        counters.forward_passes += 1
    result = features.copy()
    raw_return = np.full(len(result), np.nan, dtype=float)
    realized_volatility = np.full(len(result), np.nan, dtype=float)
    for indices in result.groupby("session_date", sort=False).indices.values():
        positions = np.asarray(indices, dtype=int)
        day = result.iloc[positions]
        opens = day["open"].to_numpy(dtype=float)
        closes = day["close"].to_numpy(dtype=float)
        for anchor in range(0, len(day) - PRIMARY_HORIZON_BARS):
            window_start = anchor + 1
            window_stop = anchor + PRIMARY_HORIZON_BARS + 1
            path = np.concatenate(([opens[window_start]], closes[window_start:window_stop]))
            raw_return[positions[anchor]] = closes[window_stop - 1] / opens[window_start] - 1.0
            realized_volatility[positions[anchor]] = float(np.sqrt(np.square(np.diff(np.log(path))).sum()))
    result["forward_raw_return"] = raw_return
    result["forward_realized_volatility"] = realized_volatility
    result["forward_valid"] = np.isfinite(raw_return) & np.isfinite(realized_volatility)
    return result


def identify_events(prepared: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for factor in FACTORS:
        for session_date, day in prepared.groupby("session_date", sort=False):
            anchor = day.loc[day["time_et"].eq(factor.anchor_time_et)]
            base = {
                "factor_id": factor.factor_id,
                "name": factor.name,
                "target_type": factor.target_type,
                "anchor_time_et": factor.anchor_time_et,
                "session_date": session_date,
                "status": "OK",
                "factor_value": np.nan,
                "exposed": False,
                "effect_sign": 0,
                "forward_raw_return": np.nan,
                "forward_realized_volatility": np.nan,
            }
            if len(anchor) != 1:
                base["status"] = "MISSING_ANCHOR"
                rows.append(base)
                continue
            row = anchor.iloc[0]
            if row["bar_available_at_utc"] > row["timestamp_utc"]:
                base["status"] = "BLOCKED_PIT"
                rows.append(base)
                continue
            try:
                value = factor.value(row)
            except (KeyError, TypeError, ValueError, ZeroDivisionError):
                value = np.nan
            if not np.isfinite(value):
                base["status"] = "WARMUP_UNAVAILABLE"
                rows.append(base)
                continue
            if not bool(row["forward_valid"]):
                base["status"] = "FORWARD_WINDOW_UNAVAILABLE"
                rows.append(base)
                continue
            exposed = bool(factor.exposed(value))
            base.update(
                factor_value=float(value),
                exposed=exposed,
                effect_sign=int(factor.direction(value)),
                forward_raw_return=float(row["forward_raw_return"]),
                forward_realized_volatility=float(row["forward_realized_volatility"]),
            )
            rows.append(base)
    return pd.DataFrame(rows)


def _response(observations: pd.DataFrame, factor: FactorDefinition) -> pd.Series:
    if factor.target_type == "DIRECTION" or factor.factor_id == "F04":
        return observations["effect_sign"] * observations["forward_raw_return"] * 10_000.0
    return observations["forward_realized_volatility"]


def _safe_stat(series: pd.Series, kind: str) -> float:
    clean = series.dropna()
    if clean.empty:
        return np.nan
    return float(clean.mean() if kind == "mean" else clean.median())


def _screen_status(
    *,
    events: int,
    unique_days: int,
    lift_vs_baseline: float,
    early_lift: float,
    late_lift: float,
    max_overlap: float,
) -> tuple[str, str]:
    if events < 50 or unique_days < 40:
        return "WATCH_CAPACITY", "低于50事件或40独立日的深测排期提示"
    if not all(np.isfinite(value) for value in (lift_vs_baseline, early_lift, late_lift)):
        return "WATCH_UNSTABLE", "缺少完整的总体或60/40分段效果"
    if lift_vs_baseline <= 0 or early_lift <= 0 or late_lift <= 0:
        return "WATCH_UNSTABLE", "总体或60/40探索分段未保持同向正增量"
    if max_overlap >= 0.80:
        return "WATCH_OVERLAP", "与另一因子的独立事件日Jaccard重叠达到0.80"
    return "KEEP_FOR_DEEP_TEST", "容量、同Anchor增量及60/40方向满足预先固定的探索排期规则"


def _overlap_by_factor(observations: pd.DataFrame) -> dict[str, tuple[float, str]]:
    event_days = {
        factor.factor_id: set(
            observations.loc[
                observations["factor_id"].eq(factor.factor_id)
                & observations["status"].eq("OK")
                & observations["exposed"],
                "session_date",
            ]
        )
        for factor in FACTORS
    }
    result: dict[str, tuple[float, str]] = {}
    for factor in FACTORS:
        best_score, best_peer = 0.0, ""
        for peer in FACTORS:
            if peer.factor_id == factor.factor_id:
                continue
            union = event_days[factor.factor_id] | event_days[peer.factor_id]
            score = len(event_days[factor.factor_id] & event_days[peer.factor_id]) / len(union) if union else 0.0
            if score > best_score:
                best_score, best_peer = score, peer.factor_id
        result[factor.factor_id] = (best_score, best_peer)
    return result


def summarize(
    observations: pd.DataFrame,
    *,
    split_session_dates: list[str] | None = None,
    evidence_label: str = EVIDENCE_LABEL,
    pit_status: str = "PIT_VERIFIED_SYNTHETIC_INPUT",
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    overlap = _overlap_by_factor(observations)
    fixed_dates = sorted(split_session_dates or observations["session_date"].unique())
    split = max(1, int(len(fixed_dates) * 0.60)) if fixed_dates else 0
    early_dates, late_dates = set(fixed_dates[:split]), set(fixed_dates[split:])
    for factor in FACTORS:
        all_factor = observations.loc[observations["factor_id"].eq(factor.factor_id)].copy()
        eligible = all_factor.loc[all_factor["status"].eq("OK")].copy()
        exposed = eligible.loc[eligible["exposed"]].copy()
        eligible_response = _response(eligible, factor)
        exposed_response = _response(exposed, factor)
        early = exposed.loc[exposed["session_date"].isin(early_dates)]
        late = exposed.loc[exposed["session_date"].isin(late_dates)]
        baseline_mean = _safe_stat(eligible_response, "mean")
        no_signal = eligible.loc[~eligible["exposed"]]
        no_signal_mean = _safe_stat(_response(no_signal, factor), "mean")
        event_mean = _safe_stat(exposed_response, "mean")
        early_eligible = eligible.loc[eligible["session_date"].isin(early_dates)]
        late_eligible = eligible.loc[eligible["session_date"].isin(late_dates)]
        early_baseline = _safe_stat(_response(early_eligible, factor), "mean")
        late_baseline = _safe_stat(_response(late_eligible, factor), "mean")
        early_mean = _safe_stat(_response(early, factor), "mean")
        late_mean = _safe_stat(_response(late, factor), "mean")
        early_lift = early_mean - early_baseline if np.isfinite(early_mean) else np.nan
        late_lift = late_mean - late_baseline if np.isfinite(late_mean) else np.nan
        lift_vs_baseline = event_mean - baseline_mean if np.isfinite(event_mean) else np.nan
        max_overlap, overlap_peer = overlap[factor.factor_id]
        excluded_reasons = all_factor.loc[~all_factor["status"].eq("OK"), "status"].value_counts()
        if evidence_label == TRAIN_EVIDENCE_LABEL:
            screen_status, reason = _screen_status(
                events=len(exposed),
                unique_days=exposed["session_date"].nunique(),
                lift_vs_baseline=lift_vs_baseline,
                early_lift=early_lift,
                late_lift=late_lift,
                max_overlap=max_overlap,
            )
        else:
            screen_status, reason = EVIDENCE_LABEL, "人工数据功能演示；不构成真实市场结论"
        unit = (
            "basis_points"
            if factor.target_type == "DIRECTION" or factor.factor_id == "F04"
            else "unannualized_realized_volatility"
        )
        rows.append(
            {
                "factor_id": factor.factor_id,
                "target_type": factor.target_type,
                "events": int(len(exposed)),
                "unique_days": int(exposed["session_date"].nunique()),
                "eligible_sessions": int(len(eligible)),
                "excluded_count": int(len(all_factor) - len(eligible)),
                "excluded_reasons": ";".join(
                    f"{status}={int(count)}" for status, count in excluded_reasons.items()
                ),
                "baseline_definition": f"all eligible and no-signal sessions at {factor.anchor_time_et}; {unit}",
                "baseline_all_mean": baseline_mean,
                "baseline_no_signal_mean": no_signal_mean,
                "forward_mean": event_mean,
                "forward_median": _safe_stat(exposed_response, "median"),
                "lift_vs_baseline": lift_vs_baseline,
                "lift_vs_no_signal": event_mean - no_signal_mean if np.isfinite(event_mean) and np.isfinite(no_signal_mean) else np.nan,
                "positive_proportion": float((exposed_response > 0).mean()) if len(exposed) else np.nan,
                "early_n": int(len(early)),
                "late_n": int(len(late)),
                "early_lift": early_lift,
                "late_lift": late_lift,
                "overlap_note": f"max_event_day_jaccard={max_overlap:.6f}; peer={overlap_peer or 'NONE'}",
                "pit_status": pit_status,
                "screen_status": screen_status,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


def run_screen(
    raw: pd.DataFrame,
    counters: RunCounters | None = None,
    *,
    session_close_by_date: dict[str, str] | None = None,
    allowed_pit_statuses: frozenset[str] = frozenset({"PIT_VERIFIED"}),
    evidence_label: str = EVIDENCE_LABEL,
    pit_status: str = "PIT_VERIFIED_SYNTHETIC_INPUT",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    active_counters = counters if counters is not None else RunCounters()
    qualified = qualify_ohlc(
        raw,
        active_counters,
        session_close_by_date=session_close_by_date,
        allowed_pit_statuses=allowed_pit_statuses,
    )
    features = compute_shared_features(qualified, active_counters)
    prepared = compute_forward_responses(features, active_counters)
    observations = identify_events(prepared)
    return summarize(
        observations,
        split_session_dates=qualified["session_date"].drop_duplicates().tolist(),
        evidence_label=evidence_label,
        pit_status=pit_status,
    ), observations
