from datetime import UTC, datetime

import pandas as pd
import pytest

from tv_quant.pattern_finder.data_quality import (
    assess_symbol_data,
    latest_complete_xnys_session,
)


def _frame(days: list[str], symbol: str = "AAPL") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(days, utc=True),
            "ticker": [symbol] * len(days),
            "open": [100.0 + index for index in range(len(days))],
            "high": [102.0 + index for index in range(len(days))],
            "low": [99.0 + index for index in range(len(days))],
            "close": [101.0 + index for index in range(len(days))],
            "volume": [1_000_000 + index for index in range(len(days))],
        }
    )


def test_latest_complete_session_respects_xnys_close_and_independence_day() -> None:
    before_monday_close = datetime(2026, 7, 6, 19, 59, tzinfo=UTC)
    after_monday_close = datetime(2026, 7, 6, 20, 1, tzinfo=UTC)

    assert latest_complete_xnys_session(before_monday_close).isoformat() == "2026-07-02"
    assert latest_complete_xnys_session(after_monday_close).isoformat() == "2026-07-06"


def test_complete_xnys_data_passes_without_inventing_holiday_bar() -> None:
    data = _frame(["2026-07-01", "2026-07-02", "2026-07-06"])

    report = assess_symbol_data(data, "AAPL", datetime(2026, 7, 6, 20, 1, tzinfo=UTC))

    assert report.passed is True
    assert report.missing_sessions == ()
    assert report.expected_latest_session.isoformat() == "2026-07-06"
    assert report.last_session.isoformat() == "2026-07-06"


def test_missing_and_stale_sessions_are_reported_without_forward_fill() -> None:
    missing = assess_symbol_data(
        _frame(["2026-07-01", "2026-07-06"]),
        "AAPL",
        datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
    )
    stale = assess_symbol_data(
        _frame(["2026-07-01", "2026-07-02", "2026-07-06"]),
        "AAPL",
        datetime(2026, 7, 7, 20, 1, tzinfo=UTC),
    )

    assert missing.passed is False
    assert tuple(day.isoformat() for day in missing.missing_sessions) == ("2026-07-02",)
    assert stale.passed is False
    assert tuple(day.isoformat() for day in stale.missing_sessions) == ("2026-07-07",)
    assert any("stale" in error.lower() for error in stale.errors)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda frame: frame.assign(ticker="MSFT"), "symbol mismatch"),
        (lambda frame: pd.concat([frame, frame.iloc[[-1]]], ignore_index=True), "duplicate"),
        (lambda frame: frame.iloc[::-1].reset_index(drop=True), "strictly sorted"),
        (lambda frame: frame.assign(high=98.0), "high price"),
        (lambda frame: frame.assign(volume=-1), "non-negative"),
    ],
)
def test_structural_data_quality_failures_are_visible(mutate, expected: str) -> None:
    report = assess_symbol_data(
        mutate(_frame(["2026-07-01", "2026-07-02", "2026-07-06"])),
        "AAPL",
        datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
    )

    assert report.passed is False
    assert any(expected in error.lower() for error in report.errors)
