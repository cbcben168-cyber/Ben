from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from tv_quant.data_quality import validate_ohlcv


PATTERN_DETECTOR_VERSION = "phase1-v1"
MIN_HISTORY = 120
MIN_BASE_LENGTH = 25
MAX_BASE_LENGTH = 90
PIVOT_LEFT = 2
PIVOT_RIGHT = 2
MAX_BASE_DEPTH_PCT = 0.18
BOTTOM_TOLERANCE_PCT = 0.04
MIN_BOTTOM_TESTS = 2
MAX_ABS_NORMALIZED_SLOPE = 0.0015


@dataclass(frozen=True, slots=True)
class FlatBaseWindow:
    window_id: str
    pattern_flat_base: bool
    base_length: int
    base_start: datetime
    base_end: datetime
    base_depth_pct: float
    bottom_test_count: int
    bottom_tolerance_pct: float
    normalized_slope: float
    support_level: float
    resistance_level: float
    resistance_raw: float
    resistance_upper_quantile: float
    resistance_spike_adjusted: bool
    atr14_t0: float


@dataclass(frozen=True, slots=True)
class FlatBaseResult:
    detector_version: str
    pattern_flat_base: bool
    selected: FlatBaseWindow
    evaluated_windows: tuple[FlatBaseWindow, ...]


def _wilder_atr14(data: pd.DataFrame) -> float:
    high = data["high"].to_numpy(dtype=float)
    low = data["low"].to_numpy(dtype=float)
    close = data["close"].to_numpy(dtype=float)
    true_range = np.empty(len(data), dtype=float)
    true_range[0] = high[0] - low[0]
    true_range[1:] = np.maximum.reduce(
        (
            high[1:] - low[1:],
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1]),
        )
    )
    atr = float(true_range[:14].mean())
    for value in true_range[14:]:
        atr = (13.0 * atr + float(value)) / 14.0
    return atr


def _normalized_slope(close: np.ndarray) -> float:
    x = np.arange(len(close), dtype=float)
    centered_x = x - x.mean()
    slope = float(
        np.dot(centered_x, close - close.mean()) / np.dot(centered_x, centered_x)
    )
    return slope / float(close.mean())


def _pivot_lows(low: np.ndarray) -> tuple[float, ...]:
    pivots: list[float] = []
    for index in range(PIVOT_LEFT, len(low) - PIVOT_RIGHT):
        neighborhood = low[index - PIVOT_LEFT : index + PIVOT_RIGHT + 1]
        if low[index] == neighborhood.min():
            pivots.append(float(low[index]))
    return tuple(pivots)


def _evaluate_window(
    data: pd.DataFrame,
    length: int,
    atr14_t0: float,
) -> FlatBaseWindow:
    window = data.tail(length)
    high = window["high"].to_numpy(dtype=float)
    low = window["low"].to_numpy(dtype=float)
    close = window["close"].to_numpy(dtype=float)
    base_high = float(high.max())
    base_low = float(low.min())
    base_depth_pct = (base_high - base_low) / base_low

    pivots = _pivot_lows(low)
    if pivots:
        bottom_reference = min(pivots)
        bottom_zone = tuple(
            pivot
            for pivot in pivots
            if (pivot - bottom_reference) / bottom_reference <= BOTTOM_TOLERANCE_PCT
        )
        bottom_tolerance_pct = max(
            (pivot - bottom_reference) / bottom_reference for pivot in bottom_zone
        )
    else:
        bottom_reference = base_low
        bottom_zone = ()
        bottom_tolerance_pct = 0.0

    normalized_slope = _normalized_slope(close)
    resistance_highs = high[:-1]
    resistance_raw = float(resistance_highs.max())
    resistance_upper_quantile = float(np.quantile(resistance_highs, 0.90))
    resistance_spike_adjusted = (
        resistance_raw > resistance_upper_quantile + 1.5 * atr14_t0
    )
    resistance_level = (
        resistance_upper_quantile if resistance_spike_adjusted else resistance_raw
    )
    pattern_flat_base = (
        base_depth_pct <= MAX_BASE_DEPTH_PCT
        and len(bottom_zone) >= MIN_BOTTOM_TESTS
        and abs(normalized_slope) <= MAX_ABS_NORMALIZED_SLOPE
    )
    timestamps = pd.to_datetime(window["timestamp_utc"], utc=True)
    return FlatBaseWindow(
        window_id=f"flat-{length:03d}",
        pattern_flat_base=pattern_flat_base,
        base_length=length,
        base_start=timestamps.iloc[0].to_pydatetime(),
        base_end=timestamps.iloc[-1].to_pydatetime(),
        base_depth_pct=base_depth_pct,
        bottom_test_count=len(bottom_zone),
        bottom_tolerance_pct=bottom_tolerance_pct,
        normalized_slope=normalized_slope,
        support_level=bottom_reference,
        resistance_level=resistance_level,
        resistance_raw=resistance_raw,
        resistance_upper_quantile=resistance_upper_quantile,
        resistance_spike_adjusted=resistance_spike_adjusted,
        atr14_t0=atr14_t0,
    )


def _preference(window: FlatBaseWindow) -> tuple[float | int | str, ...]:
    return (
        -window.bottom_test_count,
        window.base_depth_pct,
        abs(window.normalized_slope),
        -window.base_length,
        window.window_id,
    )


def detect_flat_base(data: pd.DataFrame) -> FlatBaseResult:
    """Detect a Phase 1 V1 Flat Base using only the supplied completed bars."""
    validate_ohlcv(data)
    if len(data) < MIN_HISTORY:
        raise ValueError("Flat Base detection requires at least 120 daily bars")

    atr14_t0 = _wilder_atr14(data)
    evaluated = tuple(
        _evaluate_window(data, length, atr14_t0)
        for length in range(MIN_BASE_LENGTH, MAX_BASE_LENGTH + 1)
    )
    passing = tuple(window for window in evaluated if window.pattern_flat_base)
    selected = min(passing or evaluated, key=_preference)
    return FlatBaseResult(
        detector_version=PATTERN_DETECTOR_VERSION,
        pattern_flat_base=bool(passing),
        selected=selected,
        evaluated_windows=evaluated,
    )
