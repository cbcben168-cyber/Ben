from __future__ import annotations

from collections.abc import Callable, Iterable

import pandas as pd

from factor_research.phase4_mechanism_study.contracts import ADJUSTMENT_BASIS, SessionSpec
from factor_research.phase4_mechanism_study.volatility import expected_bar_ends, qualify_ohlc


def synthetic_schedule(count: int = 22, *, early_close_last: bool = False) -> list[SessionSpec]:
    dates = pd.bdate_range("2025-10-01", periods=count).strftime("%Y-%m-%d")
    return [
        SessionSpec(day, "13:00" if early_close_last and index == count - 1 else "16:00")
        for index, day in enumerate(dates)
    ]


def synthetic_frame(schedule: Iterable[SessionSpec]) -> pd.DataFrame:
    rows = []
    for spec in schedule:
        for time_et in expected_bar_ends(spec.close_time_et):
            rows.append(
                {
                    "session_date": spec.session_date,
                    "time_et": time_et,
                    "open": 100.0,
                    "high": 100.5,
                    "low": 99.5,
                    "close": 100.0,
                    "adjustment_basis": ADJUSTMENT_BASIS,
                }
            )
    return pd.DataFrame(rows)


def qualified(
    schedule: list[SessionSpec],
    mutate: Callable[[pd.DataFrame, list[SessionSpec]], None] | None = None,
):
    frame = synthetic_frame(schedule)
    if mutate:
        mutate(frame, schedule)
    return qualify_ohlc(frame, schedule, expected_session_count=len(schedule))


def set_bar(frame: pd.DataFrame, day: str, j: int, **values: float) -> None:
    indices = frame.index[frame["session_date"].eq(day)]
    frame.loc[indices[j], list(values)] = list(values.values())


def set_m01(frame: pd.DataFrame, schedule: list[SessionSpec], *, direction: int, j: int = 12) -> None:
    day = schedule[-1].session_date
    if direction == 1:
        set_bar(frame, day, j, open=99.6, high=100.0, low=99.3, close=99.8)
    else:
        set_bar(frame, day, j, open=100.4, high=100.7, low=100.0, close=100.2)


def set_m02(frame: pd.DataFrame, schedule: list[SessionSpec], *, direction: int, j: int = 24) -> None:
    day = schedule[-1].session_date
    indices = frame.index[frame["session_date"].eq(day)]
    compression = indices[j - 6 : j]
    frame.loc[compression, ["open", "high", "low", "close"]] = [100.0, 100.2, 99.8, 100.0]
    if direction == 1:
        set_bar(frame, day, j, open=100.0, high=101.5, low=99.9, close=101.5)
    else:
        set_bar(frame, day, j, open=100.0, high=100.1, low=98.5, close=98.5)


def set_m06(frame: pd.DataFrame, schedule: list[SessionSpec], *, direction: int, j: int = 1) -> None:
    day = schedule[-1].session_date
    if direction == -1:
        set_bar(frame, day, 0, open=102.0, high=102.5, low=101.5, close=102.0)
        set_bar(frame, day, j, open=101.6, high=101.7, low=100.9, close=101.0)
    else:
        set_bar(frame, day, 0, open=98.0, high=98.5, low=97.5, close=98.0)
        set_bar(frame, day, j, open=98.4, high=99.1, low=98.3, close=99.0)
