from dataclasses import FrozenInstanceError

import pandas as pd
import pytest

from tv_quant.pattern_finder.flat_base import (
    PATTERN_DETECTOR_VERSION,
    detect_flat_base,
)


def _frame(
    *,
    rows: int = 120,
    base_length: int = 30,
    base_start_close: float = 101.0,
    slope_per_day: float = 0.0,
    pivot_lows: tuple[tuple[int, float], ...] = ((5, 99.0), (20, 99.5)),
    spike: tuple[int, float] | None = None,
) -> pd.DataFrame:
    timestamps = pd.bdate_range("2025-01-02", periods=rows, tz="UTC")
    base_start = rows - base_length
    values: list[dict[str, object]] = []
    pivot_map = dict(pivot_lows)
    for index, timestamp in enumerate(timestamps):
        if index < base_start:
            close = 112.0 - 0.12 * index
            high = close + 1.0
            low = close - 1.0
        else:
            offset = index - base_start
            close = base_start_close + slope_per_day * offset
            high = close + 1.0
            low = close - 0.5 + 0.002 * offset
            if offset in pivot_map:
                low = pivot_map[offset]
            if spike is not None and offset == spike[0]:
                high = spike[1]
        values.append(
            {
                "timestamp_utc": timestamp,
                "ticker": "TEST",
                "open": close,
                "high": high,
                "low": low,
                "close": close,
                "volume": 1_000_000,
            }
        )
    return pd.DataFrame(values)


def test_clean_flat_base_passes_with_literal_frozen_diagnostics() -> None:
    result = detect_flat_base(_frame())

    assert PATTERN_DETECTOR_VERSION == "phase1-v1"
    assert result.pattern_flat_base is True
    assert 25 <= result.selected.base_length <= 90
    assert result.selected.base_depth_pct <= 0.18
    assert result.selected.bottom_test_count >= 2
    assert abs(result.selected.normalized_slope) <= 0.0015
    assert result.selected.support_level == pytest.approx(99.0)
    assert result.selected.resistance_level > result.selected.support_level
    assert result.selected.base_end == pd.Timestamp(
        "2025-06-18", tz="UTC"
    ).to_pydatetime()


def test_too_deep_base_is_a_negative_fixture() -> None:
    frame = _frame(pivot_lows=((5, 86.4), (20, 86.5)))

    result = detect_flat_base(frame)

    assert result.pattern_flat_base is False
    assert result.selected.base_depth_pct > 0.18
    assert result.selected.base_depth_pct < 0.181


def test_unstable_lows_are_a_negative_fixture() -> None:
    frame = _frame(pivot_lows=((5, 96.0), (20, 99.85)))

    result = detect_flat_base(frame)

    assert result.pattern_flat_base is False
    assert result.selected.bottom_test_count == 1
    assert (99.85 - 96.0) / 96.0 > 0.04
    assert (99.85 - 96.0) / 96.0 < 0.041


def test_slope_just_above_frozen_gate_is_a_near_miss() -> None:
    frame = _frame(
        base_length=90,
        base_start_close=100.0,
        slope_per_day=0.17,
        pivot_lows=(
            (5, 99.0),
            (20, 99.4),
            (35, 99.2),
            (50, 99.3),
            (65, 99.1),
            (80, 99.2),
        ),
    )

    result = detect_flat_base(frame)

    assert result.pattern_flat_base is False
    assert result.selected.normalized_slope > 0.0015
    assert result.selected.normalized_slope < 0.0017


def test_resistance_spike_uses_visible_quantile_adjustment() -> None:
    frame = _frame(spike=(10, 116.5))

    result = detect_flat_base(frame)

    assert result.pattern_flat_base is True
    assert result.selected.resistance_raw == pytest.approx(116.5)
    assert result.selected.resistance_spike_adjusted is True
    assert result.selected.resistance_level == pytest.approx(
        result.selected.resistance_upper_quantile
    )
    assert result.selected.resistance_level < 103.0


def test_multiple_windows_choose_more_bottom_tests_then_longer_window() -> None:
    frame = _frame(
        rows=160,
        base_length=90,
        pivot_lows=(
            (5, 99.0),
            (20, 99.4),
            (35, 99.2),
            (50, 99.3),
            (65, 99.1),
            (80, 99.2),
        ),
    )

    result = detect_flat_base(frame)

    assert result.pattern_flat_base is True
    assert result.selected.base_length == 90
    assert result.selected.bottom_test_count == 6
    assert len(result.evaluated_windows) == 66


def test_detector_requires_120_bars_and_does_not_mutate_input() -> None:
    short = _frame(rows=119)
    with pytest.raises(ValueError, match="120"):
        detect_flat_base(short)

    frame = _frame()
    before = frame.copy(deep=True)
    result = detect_flat_base(frame)

    pd.testing.assert_frame_equal(frame, before)
    with pytest.raises(FrozenInstanceError):
        result.pattern_flat_base = False  # type: ignore[misc]
