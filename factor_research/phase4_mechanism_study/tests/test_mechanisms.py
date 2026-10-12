from __future__ import annotations

import pytest

from factor_research.phase4_mechanism_study.mechanisms import scan_m01, scan_m02, scan_m06
from factor_research.phase4_mechanism_study.simulator import replay_scan
from factor_research.phase4_mechanism_study.volatility import qualify_ohlc

from .conftest import qualified, set_bar, set_m01, set_m02, set_m06, synthetic_frame, synthetic_schedule


@pytest.mark.parametrize("direction", [1, -1])
def test_m01_long_and_short_use_prior_twelve_only(direction: int) -> None:
    schedule = synthetic_schedule(2)
    data = qualified(schedule, lambda frame, specs: set_m01(frame, specs, direction=direction))
    result = scan_m01(data, schedule[-1].session_date)
    assert result.signal is not None
    assert result.signal.direction == direction
    assert result.signal.bar_in_session == 12
    assert result.signal.anchors["range_slice"] == [0, 12]
    assert result.signal.anchors["range_high"] == pytest.approx(100.5)
    assert result.signal.anchors["range_low"] == pytest.approx(99.5)
    assert (result.signal.stop_price < result.signal.anchors["signal_ohlc"][3]) == (direction == 1)


def test_m01_first_train_day_waits_for_global_atr_and_equal_boundary_passes() -> None:
    schedule = synthetic_schedule(1)
    frame = synthetic_frame(schedule)
    day = schedule[0].session_date
    set_bar(frame, day, 20, open=99.6, high=100.0, low=99.4, close=99.8)
    data = qualify_ohlc(frame, schedule, expected_session_count=1)
    signal = scan_m01(data, day).signal
    assert signal is not None
    assert signal.bar_in_session == 20
    assert signal.signal_time_et == "11:15"


@pytest.mark.parametrize("direction", [1, -1])
def test_m02_long_short_and_four_disjoint_six_bar_windows(direction: int) -> None:
    schedule = synthetic_schedule(2)
    data = qualified(schedule, lambda frame, specs: set_m02(frame, specs, direction=direction))
    signal = scan_m02(data, schedule[-1].session_date).signal
    assert signal is not None and signal.direction == direction
    assert signal.bar_in_session == 24 and signal.signal_time_et == "11:35"
    windows = signal.anchors["reference_slices"] + [signal.anchors["compression_slice"]]
    positions = [p for start, end in windows for p in range(start, end)]
    assert len(positions) == len(set(positions)) == 24
    assert all(end - start == 6 for start, end in windows)
    assert signal.anchors["compression_slice"][1] == signal.bar_in_session


def test_m02_equal_thresholds_pass_without_signal_bar_self_reference() -> None:
    schedule = synthetic_schedule(2)
    frame = synthetic_frame(schedule)
    day = schedule[-1].session_date
    indices = frame.index[frame["session_date"].eq(day)]
    frame.loc[indices[18:24], ["open", "high", "low", "close"]] = [100.0, 100.3, 99.7, 100.0]
    set_bar(frame, day, 24, open=100.0, high=100.4, low=98.9, close=100.4)
    data = qualify_ohlc(frame, schedule, expected_session_count=2)
    signal = scan_m02(data, day).signal
    assert signal is not None
    assert signal.anchors["compression_width"] == pytest.approx(0.6)
    assert signal.anchors["tr_reference_slice"] == [0, 24]


@pytest.mark.parametrize("direction", [1, -1])
def test_m06_true_gap_fill_long_and_short_start_at_second_bar(direction: int) -> None:
    schedule = synthetic_schedule(22)
    data = qualified(schedule, lambda frame, specs: set_m06(frame, specs, direction=direction))
    signal = scan_m06(data, schedule[-1].session_date).signal
    assert signal is not None and signal.direction == direction
    assert signal.bar_in_session == 1 and signal.signal_time_et == "09:40"
    assert signal.anchors["previous_bar_position"] == 0
    assert signal.anchors["candidate_positions"] == [1, 2, 3, 4, 5]
    assert (signal.target_value > signal.anchors["signal_ohlc"][3]) == (direction == 1)


def test_m06_equal_gap_threshold_passes_and_j6_is_forbidden() -> None:
    schedule = synthetic_schedule(22)
    frame = synthetic_frame(schedule)
    day = schedule[-1].session_date
    set_bar(frame, day, 0, open=100.5, high=100.6, low=100.4, close=100.5)
    set_bar(frame, day, 1, open=100.4, high=100.45, low=100.25, close=100.3)
    data = qualify_ohlc(frame, schedule, expected_session_count=22)
    assert scan_m06(data, day).signal is not None

    frame = synthetic_frame(schedule)
    set_bar(frame, day, 0, open=102.0, high=102.5, low=101.5, close=102.0)
    for j in range(1, 6):
        set_bar(frame, day, j, open=102.0, high=102.1, low=101.5, close=102.0)
    set_bar(frame, day, 6, open=101.6, high=101.7, low=100.9, close=101.0)
    data = qualify_ohlc(frame, schedule, expected_session_count=22)
    assert scan_m06(data, day).signal is None
    assert scan_m06(data, day).evaluated_positions == (1, 2, 3, 4, 5)


def test_setup_shortage_and_gap_prior_touch_produce_no_signal() -> None:
    schedule = synthetic_schedule(22)
    data = qualified(schedule)
    day = schedule[-1].session_date
    assert scan_m01(data, day).signal is None
    assert scan_m02(data, day).signal is None
    frame = synthetic_frame(schedule)
    set_m06(frame, schedule, direction=-1)
    set_bar(frame, day, 0, open=102.0, high=102.5, low=100.0, close=102.0)
    touched = qualify_ohlc(frame, schedule, expected_session_count=22)
    assert scan_m06(touched, day).signal is None


def test_first_complete_signal_consumes_day_even_when_next_open_cancels() -> None:
    schedule = synthetic_schedule(2)
    frame = synthetic_frame(schedule)
    set_m01(frame, schedule, direction=1, j=12)
    day = schedule[-1].session_date
    set_bar(frame, day, 13, open=100.1, high=100.2, low=100.0, close=100.1)
    set_bar(frame, day, 14, open=99.6, high=100.0, low=99.3, close=99.8)
    data = qualify_ohlc(frame, schedule, expected_session_count=2)
    scan = scan_m01(data, day)
    replay = replay_scan(data, scan)
    assert scan.signal is not None and scan.signal.bar_in_session == 12
    assert replay.status == "SIGNAL_CANCELED"
    assert replay.cancellation_reason == "INVALID_TARGET_GEOMETRY"


def test_early_close_signal_cutoffs_are_schedule_based() -> None:
    schedule = synthetic_schedule(2, early_close_last=True)
    frame = synthetic_frame(schedule)
    day = schedule[-1].session_date
    set_bar(frame, day, 36, open=99.6, high=100.0, low=99.3, close=99.8)  # 12:35, too late for M01
    data = qualify_ohlc(frame, schedule, expected_session_count=2)
    assert scan_m01(data, day).signal is None
    assert max(scan_m01(data, day).evaluated_positions) == 35  # 12:30 is last eligible signal bar
