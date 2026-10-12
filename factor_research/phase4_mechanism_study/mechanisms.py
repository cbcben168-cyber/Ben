from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import numpy as np
import pandas as pd

from .contracts import Phase4ContractError, assert_as_of_positions, assert_strict_past_window
from .volatility import QualifiedData


@dataclass(frozen=True)
class Signal:
    hypothesis_id: str
    session_date: str
    bar_in_session: int
    global_pos: int
    signal_time_et: str
    direction: int
    stop_price: float
    target_kind: str
    target_value: float
    holding_bars: int
    anchors: dict[str, Any]


@dataclass(frozen=True)
class ScanResult:
    hypothesis_id: str
    session_date: str
    status: str
    signal: Signal | None
    evaluated_positions: tuple[int, ...]


def _minutes(clock: str) -> int:
    hour, minute = (int(v) for v in clock.split(":"))
    return hour * 60 + minute


def _holding_fits(signal_time: str, holding_bars: int, close_time: str) -> bool:
    return _minutes(signal_time) + holding_bars * 5 <= _minutes(close_time)


def _result(hypothesis_id: str, session_date: str, status: str, signal: Signal | None, seen: list[int]) -> ScanResult:
    return ScanResult(hypothesis_id, session_date, status, signal, tuple(seen))


def scan_m01(data: QualifiedData, session_date: str) -> ScanResult:
    hypothesis_id = "P4_M01_ALL"
    day = data.session(session_date).reset_index(drop=True)
    close_time = data.close_time(session_date)
    seen: list[int] = []
    atr_available = False
    for j in range(12, len(day)):
        row = day.iloc[j]
        atr = float(row["intraday_atr20"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        atr_available = True
        if not _holding_fits(str(row["time_et"]), 6, close_time):
            break
        seen.append(j)
        assert_strict_past_window(j - 12, j, j, 12)
        prior = day.iloc[j - 12 : j]
        if len(prior) != 12 or j in prior.index:
            raise Phase4ContractError("M01_WINDOW_SELF_REFERENCE")
        range_low = float(prior["low"].min())
        range_high = float(prior["high"].max())
        midpoint = (range_low + range_high) / 2.0
        direction = 0
        if row["low"] <= range_low - 0.10 * atr and row["close"] > range_low and row["close"] > row["open"]:
            direction = 1
            stop = float(row["low"] - 0.25 * atr)
        elif row["high"] >= range_high + 0.10 * atr and row["close"] < range_high and row["close"] < row["open"]:
            direction = -1
            stop = float(row["high"] + 0.25 * atr)
        else:
            continue
        signal = Signal(
            hypothesis_id,
            session_date,
            j,
            int(row["global_pos"]),
            str(row["time_et"]),
            direction,
            stop,
            "FIXED_PRICE",
            midpoint,
            6,
            {
                "range_slice": [j - 12, j],
                "range_low": range_low,
                "range_high": range_high,
                "intraday_atr20": atr,
                "signal_ohlc": [float(row[c]) for c in ("open", "high", "low", "close")],
            },
        )
        return _result(hypothesis_id, session_date, "SIGNAL_CONSUMED", signal, seen)
    status = "WARMUP_UNAVAILABLE" if not atr_available else "NO_COMPLETE_SIGNAL"
    return _result(hypothesis_id, session_date, status, None, seen)


def _box_width(frame: pd.DataFrame) -> float:
    return float(frame["high"].max() - frame["low"].min())


def scan_m02(data: QualifiedData, session_date: str) -> ScanResult:
    hypothesis_id = "P4_M02_ALL"
    day = data.session(session_date).reset_index(drop=True)
    close_time = data.close_time(session_date)
    seen: list[int] = []
    atr_available = False
    for j in range(24, len(day)):
        row = day.iloc[j]
        atr = float(row["intraday_atr20"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        atr_available = True
        if not _holding_fits(str(row["time_et"]), 12, close_time):
            break
        seen.append(j)
        ref_slices = ((j - 24, j - 18), (j - 18, j - 12), (j - 12, j - 6))
        compression_slice = (j - 6, j)
        assert_strict_past_window(j - 24, j, j, 24)
        assert_as_of_positions([position for bounds in (*ref_slices, compression_slice) for position in range(*bounds)], j)
        if len({p for bounds in (*ref_slices, compression_slice) for p in range(*bounds)}) != 24:
            raise Phase4ContractError("M02_OVERLAPPING_WINDOWS")
        references = [day.iloc[start:end] for start, end in ref_slices]
        compression = day.iloc[compression_slice[0] : compression_slice[1]]
        tr_reference = day["intraday_tr"].iloc[j - 24 : j]
        if any(len(frame) != 6 for frame in (*references, compression)) or len(tr_reference) != 24:
            raise Phase4ContractError("M02_WINDOW_LENGTH")
        reference_width_median = float(np.median([_box_width(frame) for frame in references]))
        compression_low = float(compression["low"].min())
        compression_high = float(compression["high"].max())
        compression_width = compression_high - compression_low
        tr_median = float(tr_reference.median())
        common = (
            compression_width <= 0.60 * reference_width_median
            and float(row["intraday_tr"]) >= 1.50 * tr_median
            and compression_low <= float(row["open"]) <= compression_high
        )
        direction = 0
        if common and row["close"] >= compression_high + 0.10 * atr:
            direction = 1
            stop = compression_low - 0.10 * atr
        elif common and row["close"] <= compression_low - 0.10 * atr:
            direction = -1
            stop = compression_high + 0.10 * atr
        else:
            continue
        signal = Signal(
            hypothesis_id,
            session_date,
            j,
            int(row["global_pos"]),
            str(row["time_et"]),
            direction,
            float(stop),
            "ENTRY_R_MULTIPLE",
            1.5,
            12,
            {
                "reference_slices": [list(v) for v in ref_slices],
                "compression_slice": list(compression_slice),
                "tr_reference_slice": [j - 24, j],
                "reference_width_median": reference_width_median,
                "compression_low": compression_low,
                "compression_high": compression_high,
                "compression_width": compression_width,
                "tr_median": tr_median,
                "intraday_atr20": atr,
                "signal_ohlc": [float(row[c]) for c in ("open", "high", "low", "close")],
            },
        )
        return _result(hypothesis_id, session_date, "SIGNAL_CONSUMED", signal, seen)
    status = "WARMUP_UNAVAILABLE" if not atr_available else "NO_COMPLETE_SIGNAL"
    return _result(hypothesis_id, session_date, status, None, seen)


def scan_m06(data: QualifiedData, session_date: str) -> ScanResult:
    hypothesis_id = "P4_M06_ALL"
    day = data.session(session_date).reset_index(drop=True)
    daily = data.daily.loc[session_date]
    close_time = data.close_time(session_date)
    daily_atr = float(daily["daily_atr20"])
    previous_close = float(daily["previous_close"])
    if not np.isfinite(daily_atr) or daily_atr <= 0 or not np.isfinite(previous_close):
        return _result(hypothesis_id, session_date, "WARMUP_UNAVAILABLE", None, [])
    session_open = float(day.iloc[0]["open"])
    gap = session_open - previous_close
    if abs(gap) < 0.50 * daily_atr:
        return _result(hypothesis_id, session_date, "NO_COMPLETE_SIGNAL", None, [])
    seen: list[int] = []
    for j in range(1, min(6, len(day))):
        row = day.iloc[j]
        atr = float(row["intraday_atr20"])
        if not np.isfinite(atr) or atr <= 0:
            continue
        if not _holding_fits(str(row["time_et"]), 12, close_time):
            break
        seen.append(j)
        prior = day.iloc[j - 1]
        through_signal = day.iloc[: j + 1]
        assert_as_of_positions(list(range(j + 1)), j)
        fill_boundary = session_open - 0.25 * gap
        direction = 0
        if (
            gap > 0
            and float(through_signal["low"].min()) > previous_close
            and previous_close < float(row["close"]) <= fill_boundary
            and float(row["close"]) < float(prior["low"])
            and float(row["close"]) < float(row["open"])
        ):
            direction = -1
            stop = float(through_signal["high"].max() + 0.10 * atr)
        elif (
            gap < 0
            and float(through_signal["high"].max()) < previous_close
            and fill_boundary <= float(row["close"]) < previous_close
            and float(row["close"]) > float(prior["high"])
            and float(row["close"]) > float(row["open"])
        ):
            direction = 1
            stop = float(through_signal["low"].min() - 0.10 * atr)
        else:
            continue
        signal = Signal(
            hypothesis_id,
            session_date,
            j,
            int(row["global_pos"]),
            str(row["time_et"]),
            direction,
            stop,
            "FIXED_PRICE",
            previous_close,
            12,
            {
                "candidate_positions": [1, 2, 3, 4, 5],
                "previous_bar_position": j - 1,
                "previous_close": previous_close,
                "session_open": session_open,
                "gap": gap,
                "daily_atr20": daily_atr,
                "fill_boundary": fill_boundary,
                "through_signal_slice": [0, j + 1],
                "intraday_atr20": atr,
                "signal_ohlc": [float(row[c]) for c in ("open", "high", "low", "close")],
            },
        )
        return _result(hypothesis_id, session_date, "SIGNAL_CONSUMED", signal, seen)
    return _result(hypothesis_id, session_date, "NO_COMPLETE_SIGNAL", None, seen)


SCANNERS: dict[str, Callable[[QualifiedData, str], ScanResult]] = {
    "P4_M01_ALL": scan_m01,
    "P4_M02_ALL": scan_m02,
    "P4_M06_ALL": scan_m06,
}


def scan_all(data: QualifiedData, session_date: str) -> dict[str, ScanResult]:
    return {name: scanner(data, session_date) for name, scanner in SCANNERS.items()}
