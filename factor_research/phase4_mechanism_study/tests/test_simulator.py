from __future__ import annotations

from dataclasses import replace

import pytest

from factor_research.phase4_mechanism_study.contracts import DataIncompleteError
from factor_research.phase4_mechanism_study.mechanisms import Signal
from factor_research.phase4_mechanism_study.simulator import replay_signal
from factor_research.phase4_mechanism_study.volatility import qualify_ohlc

from .conftest import set_bar, synthetic_frame, synthetic_schedule


def _scenario(*, direction: int = 1, stop: float = 99.0, target: float = 101.0, holding: int = 2, mutate=None, hypothesis="P4_M01_ALL", target_kind="FIXED_PRICE"):
    schedule = synthetic_schedule(2)
    frame = synthetic_frame(schedule)
    day = schedule[-1].session_date
    set_bar(frame, day, 13, open=100.0, high=100.5, low=99.5, close=100.0)
    set_bar(frame, day, 14, open=100.0, high=100.5, low=99.5, close=100.2)
    if mutate:
        mutate(frame, day)
    data = qualify_ohlc(frame, schedule, expected_session_count=2)
    row = data.session(day).reset_index(drop=True).iloc[12]
    signal = Signal(
        hypothesis, day, 12, int(row["global_pos"]), str(row["time_et"]), direction,
        stop, target_kind, target, holding, {"synthetic": True},
    )
    return data, signal


def test_same_bar_dual_hit_obeys_stop_first_and_target_first_sensitivity() -> None:
    data, signal = _scenario(mutate=lambda f, d: set_bar(f, d, 13, open=100.0, high=102.0, low=98.0, close=100.0))
    result = replay_signal(data, signal)
    assert result.exit_reason_stop_first == "STOP_SAME_BAR"
    assert result.exit_price_stop_first == 99.0
    assert result.exit_reason_target_first == "TARGET_SAME_BAR"
    assert result.exit_price_target_first == 101.0


@pytest.mark.parametrize(
    ("open_price", "expected_reason", "expected_price"),
    [(98.5, "GAP_STOP", 98.5), (101.5, "GAP_TARGET_CAPPED", 101.0)],
)
def test_gap_stop_and_gap_target_contract(open_price: float, expected_reason: str, expected_price: float) -> None:
    data, signal = _scenario(mutate=lambda f, d: set_bar(f, d, 14, open=open_price, high=max(open_price, 100.0), low=min(open_price, 100.0), close=open_price))
    result = replay_signal(data, signal)
    assert result.exit_reason_stop_first == expected_reason
    assert result.exit_price_stop_first == expected_price


def test_time_exit_uses_last_allowed_bar_close() -> None:
    data, signal = _scenario(stop=90.0, target=110.0)
    result = replay_signal(data, signal)
    assert result.exit_reason_stop_first == "TIME"
    assert result.exit_price_stop_first == pytest.approx(100.2)


@pytest.mark.parametrize("hypothesis", ["P4_M01_ALL", "P4_M02_ALL", "P4_M06_ALL"])
def test_non_positive_net_target_gate_applies_to_every_mechanism(hypothesis: str) -> None:
    data, signal = _scenario(target=100.04, hypothesis=hypothesis)
    result = replay_signal(data, signal)
    assert result.status == "SIGNAL_CANCELED"
    assert result.cancellation_reason == "NON_POSITIVE_NET_TARGET"


def test_stop_and_target_geometry_fail_closed() -> None:
    data, bad_stop = _scenario(stop=100.0, target=101.0)
    assert replay_signal(data, bad_stop).cancellation_reason == "INVALID_STOP_GEOMETRY"
    data, crossed = _scenario(direction=-1, stop=101.0, target=100.5, hypothesis="P4_M06_ALL")
    assert replay_signal(data, crossed).cancellation_reason == "GAP_TARGET_ALREADY_CROSSED"


def test_m02_target_is_exactly_one_point_five_initial_r() -> None:
    data, signal = _scenario(stop=99.0, target=1.5, hypothesis="P4_M02_ALL", target_kind="ENTRY_R_MULTIPLE")
    result = replay_signal(data, signal)
    assert result.target_price == pytest.approx(101.5)
    assert result.stop_price < result.entry_price < result.target_price


def test_missing_required_future_data_blocks_whole_replay_not_trade_only() -> None:
    data, signal = _scenario()
    entry_global = signal.global_pos + 1
    damaged = replace(data, bars=data.bars.loc[data.bars["global_pos"] != entry_global].copy())
    with pytest.raises(DataIncompleteError, match="REQUIRED_FUTURE_BAR"):
        replay_signal(damaged, signal)


def test_invalid_data_gate_status_cannot_be_replayed() -> None:
    data, signal = _scenario()
    with pytest.raises(DataIncompleteError, match="DATA_GATE_NOT_PASS"):
        replay_signal(replace(data, data_gate_status="DATA_INCOMPLETE"), signal)
