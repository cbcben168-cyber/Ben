from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from .contracts import (
    ADJUSTMENT_BASIS,
    TRAIN_END,
    TRAIN_SESSIONS,
    TRAIN_START,
    DataIncompleteError,
    Phase4ContractError,
    SessionSpec,
)

BAR_COLUMNS = ("session_date", "time_et", "open", "high", "low", "close", "adjustment_basis")


@dataclass(frozen=True)
class QualifiedData:
    bars: pd.DataFrame
    daily: pd.DataFrame
    schedule: tuple[SessionSpec, ...]
    data_gate_status: str = "PASS"

    def session(self, session_date: str) -> pd.DataFrame:
        return self.bars.loc[self.bars["session_date"] == session_date].copy()

    def close_time(self, session_date: str) -> str:
        return next(s.close_time_et for s in self.schedule if s.session_date == session_date)


def expected_bar_ends(close_time_et: str) -> list[str]:
    try:
        times = pd.date_range("2000-01-01 09:35", f"2000-01-01 {close_time_et}", freq="5min")
    except (TypeError, ValueError) as exc:
        raise Phase4ContractError("INVALID_SCHEDULE_CLOSE") from exc
    if not len(times) or times[-1].strftime("%H:%M") != close_time_et:
        raise Phase4ContractError("INVALID_SCHEDULE_CLOSE")
    return list(times.strftime("%H:%M"))


def _validate_schedule(
    schedule: Iterable[SessionSpec], expected_session_count: int | None
) -> tuple[SessionSpec, ...]:
    result = tuple(schedule)
    dates = [s.session_date for s in result]
    if expected_session_count is not None and len(result) != expected_session_count:
        raise DataIncompleteError("DATA_INCOMPLETE: SESSION_COUNT")
    if len(set(dates)) != len(dates) or dates != sorted(dates):
        raise Phase4ContractError("INVALID_SESSION_SCHEDULE")
    if any(d < TRAIN_START or d > TRAIN_END for d in dates):
        raise Phase4ContractError("UNAUTHORIZED_NON_TRAIN_SESSION")
    for spec in result:
        expected_bar_ends(spec.close_time_et)
    return result


def qualify_ohlc(
    raw: pd.DataFrame,
    schedule: Iterable[SessionSpec],
    *,
    expected_session_count: int | None = TRAIN_SESSIONS,
) -> QualifiedData:
    """Globally qualify a complete TRAIN-only 5-minute RTH grid.

    Synthetic tests explicitly pass their synthetic session count. A research run
    must retain the default 187-session requirement.
    """

    specs = _validate_schedule(schedule, expected_session_count)
    missing_columns = sorted(set(BAR_COLUMNS).difference(raw.columns))
    if missing_columns:
        raise DataIncompleteError(f"DATA_INCOMPLETE: COLUMNS={missing_columns}")
    bars = raw.loc[:, BAR_COLUMNS].copy()
    if bars.empty:
        raise DataIncompleteError("DATA_INCOMPLETE: EMPTY")
    bars["session_date"] = bars["session_date"].astype(str)
    bars["time_et"] = bars["time_et"].astype(str)
    if bars.duplicated(["session_date", "time_et"]).any():
        raise DataIncompleteError("DATA_INCOMPLETE: DUPLICATE_BAR")
    expected_pairs = [
        (spec.session_date, time_et)
        for spec in specs
        for time_et in expected_bar_ends(spec.close_time_et)
    ]
    actual_pairs = list(zip(bars["session_date"], bars["time_et"]))
    if actual_pairs != expected_pairs:
        raise DataIncompleteError("DATA_INCOMPLETE: REQUIRED_RTH_GRID")
    numeric = bars.loc[:, ["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise DataIncompleteError("DATA_INCOMPLETE: NONFINITE_OHLC")
    if (numeric <= 0).any().any():
        raise Phase4ContractError("INVALID_NONPOSITIVE_PRICE")
    bars.loc[:, ["open", "high", "low", "close"]] = numeric
    if ((bars["high"] < bars[["open", "close", "low"]].max(axis=1)) | (
        bars["low"] > bars[["open", "close", "high"]].min(axis=1)
    )).any():
        raise Phase4ContractError("INVALID_OHLC_ENVELOPE")
    if not (bars["adjustment_basis"] == ADJUSTMENT_BASIS).all():
        raise Phase4ContractError("ADJUSTMENT_BASIS_MISMATCH")

    bars["global_pos"] = np.arange(len(bars), dtype=int)
    bars["bar_in_session"] = bars.groupby("session_date", sort=False).cumcount()
    previous_close = bars.groupby("session_date", sort=False)["close"].shift(1)
    high_low = bars["high"] - bars["low"]
    true_range = pd.concat(
        [high_low, (bars["high"] - previous_close).abs(), (bars["low"] - previous_close).abs()],
        axis=1,
    ).max(axis=1, skipna=True)
    first_bar = bars["bar_in_session"].eq(0)
    true_range.loc[first_bar] = high_low.loc[first_bar]
    bars["intraday_tr"] = true_range.astype(float)
    bars["intraday_atr20"] = bars["intraday_tr"].shift(1).rolling(20, min_periods=20).mean()

    daily = bars.groupby("session_date", sort=False).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
    )
    daily["previous_close"] = daily["close"].shift(1)
    daily["daily_tr"] = pd.concat(
        [
            daily["high"] - daily["low"],
            (daily["high"] - daily["previous_close"]).abs(),
            (daily["low"] - daily["previous_close"]).abs(),
        ],
        axis=1,
    ).max(axis=1, skipna=False)
    daily["daily_atr20"] = daily["daily_tr"].shift(1).rolling(20, min_periods=20).mean()
    daily["session_index"] = np.arange(len(daily), dtype=int)
    return QualifiedData(bars=bars, daily=daily, schedule=specs)
