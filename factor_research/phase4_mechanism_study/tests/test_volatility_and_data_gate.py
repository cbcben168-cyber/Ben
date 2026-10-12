from __future__ import annotations

import pandas as pd
import pytest

from factor_research.phase4_mechanism_study.contracts import (
    DataIncompleteError,
    Phase4ContractError,
    SessionSpec,
)
from factor_research.phase4_mechanism_study.volatility import expected_bar_ends, qualify_ohlc

from .conftest import qualified, set_bar, set_m01, synthetic_frame, synthetic_schedule


def test_atr20_uses_exact_previous_twenty_and_excludes_current() -> None:
    schedule = synthetic_schedule(1)
    frame = synthetic_frame(schedule)
    day = schedule[0].session_date
    for j, width in enumerate(range(1, 22)):
        set_bar(frame, day, j, open=100.0, high=100.0 + width / 2, low=100.0 - width / 2, close=100.0)
    data = qualify_ohlc(frame, schedule, expected_session_count=1)
    assert pd.isna(data.bars.iloc[19]["intraday_atr20"])
    assert data.bars.iloc[20]["intraday_atr20"] == pytest.approx(sum(range(1, 21)) / 20)
    assert data.bars.iloc[20]["intraday_tr"] == pytest.approx(21.0)


def test_first_rth_bar_tr_excludes_overnight_gap_and_atr_crosses_sessions() -> None:
    schedule = synthetic_schedule(2)
    frame = synthetic_frame(schedule)
    day2 = schedule[1].session_date
    set_bar(frame, day2, 0, open=110.0, high=111.0, low=109.0, close=110.0)
    data = qualify_ohlc(frame, schedule, expected_session_count=2)
    first = data.session(day2).iloc[0]
    assert first["intraday_tr"] == pytest.approx(2.0)
    assert first["intraday_atr20"] == pytest.approx(1.0)


def test_daily_atr_first_available_only_on_twenty_second_train_session() -> None:
    data = qualified(synthetic_schedule(22))
    assert data.daily.iloc[:21]["daily_atr20"].isna().all()
    assert data.daily.iloc[21]["daily_atr20"] == pytest.approx(1.0)


def test_early_close_grid_ends_at_known_1300() -> None:
    schedule = synthetic_schedule(1, early_close_last=True)
    data = qualified(schedule)
    assert len(data.bars) == len(expected_bar_ends("13:00")) == 42
    assert data.bars.iloc[-1]["time_et"] == "13:00"


def test_missing_future_bar_fails_global_data_gate() -> None:
    schedule = synthetic_schedule(1)
    frame = synthetic_frame(schedule).drop(index=30).reset_index(drop=True)
    with pytest.raises(DataIncompleteError, match="REQUIRED_RTH_GRID"):
        qualify_ohlc(frame, schedule, expected_session_count=1)


def test_adjustment_basis_mismatch_and_non_train_session_fail_closed() -> None:
    schedule = synthetic_schedule(1)
    frame = synthetic_frame(schedule)
    frame.loc[0, "adjustment_basis"] = "OTHER"
    with pytest.raises(Phase4ContractError, match="ADJUSTMENT_BASIS_MISMATCH"):
        qualify_ohlc(frame, schedule, expected_session_count=1)
    bad_schedule = [SessionSpec("2025-09-30", "16:00")]
    with pytest.raises(Phase4ContractError, match="UNAUTHORIZED_NON_TRAIN_SESSION"):
        qualify_ohlc(synthetic_frame(bad_schedule), bad_schedule, expected_session_count=1)


def test_duplicate_and_nonfinite_bars_fail_closed() -> None:
    schedule = synthetic_schedule(1)
    frame = synthetic_frame(schedule)
    duplicate = pd.concat([frame.iloc[[0]], frame], ignore_index=True)
    with pytest.raises(DataIncompleteError, match="DUPLICATE_BAR"):
        qualify_ohlc(duplicate, schedule, expected_session_count=1)
    frame.loc[0, "close"] = float("nan")
    with pytest.raises(DataIncompleteError, match="NONFINITE_OHLC"):
        qualify_ohlc(frame, schedule, expected_session_count=1)


def test_prefix_invariance_for_already_emitted_signal() -> None:
    from factor_research.phase4_mechanism_study.mechanisms import scan_m01

    short_schedule = synthetic_schedule(2)
    short_frame = synthetic_frame(short_schedule)
    set_m01(short_frame, short_schedule, direction=1)
    short_data = qualify_ohlc(short_frame, short_schedule, expected_session_count=2)
    signal_before = scan_m01(short_data, short_schedule[-1].session_date).signal

    extended_schedule = synthetic_schedule(3)
    extended_frame = synthetic_frame(extended_schedule)
    target_day = short_schedule[-1].session_date
    set_bar(extended_frame, target_day, 12, open=99.6, high=100.0, low=99.3, close=99.8)
    extended_data = qualify_ohlc(extended_frame, extended_schedule, expected_session_count=3)
    signal_after = scan_m01(extended_data, target_day).signal
    assert signal_before is not None and signal_after is not None
    assert signal_before == signal_after
