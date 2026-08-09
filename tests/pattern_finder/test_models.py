from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta, timezone
from math import nan

import pytest

from tv_quant.pattern_finder.models import ChartFixture, DailyBar


def _bar(day: int, **changes: object) -> DailyBar:
    values: dict[str, object] = {
        "timestamp_utc": datetime(2025, 1, 1, tzinfo=UTC) + timedelta(days=day),
        "open": 100.0,
        "high": 102.0,
        "low": 99.0,
        "close": 101.0,
        "volume": 1_000,
    }
    values.update(changes)
    return DailyBar(**values)  # type: ignore[arg-type]


def _bars() -> tuple[DailyBar, ...]:
    return tuple(_bar(day) for day in range(120))


def test_daily_bar_accepts_valid_utc_ohlcv_and_is_frozen() -> None:
    bar = _bar(0)

    assert bar.timestamp_utc == datetime(2025, 1, 1, tzinfo=UTC)
    assert bar.volume == 1_000
    with pytest.raises(FrozenInstanceError):
        bar.close = 99.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "changes",
    [
        {"timestamp_utc": datetime(2025, 1, 1)},
        {"timestamp_utc": datetime(2025, 1, 1, tzinfo=timezone(timedelta(hours=-5)))},
        {"open": 0.0},
        {"close": nan},
        {"high": 100.0, "open": 101.0},
        {"low": 101.5, "close": 101.0},
        {"volume": -1},
    ],
)
def test_daily_bar_rejects_invalid_time_or_ohlcv(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        _bar(0, **changes)


def test_chart_fixture_accepts_valid_metadata_and_is_frozen() -> None:
    bars = _bars()
    fixture = ChartFixture(
        symbol="TEST_FLAT",
        pattern_label="Flat fixture",
        bars=bars,
        base_start=bars[90].timestamp_utc,
        base_end=bars[-1].timestamp_utc,
        support=98.0,
        resistance=103.0,
    )

    assert fixture.symbol == "TEST_FLAT"
    assert len(fixture.bars) == 120
    with pytest.raises(FrozenInstanceError):
        fixture.support = 97.0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("symbol", "test_flat"),
        ("pattern_label", ""),
        ("base_start", datetime(2024, 1, 1, tzinfo=UTC)),
        ("base_end", datetime(2026, 1, 1, tzinfo=UTC)),
        ("support", 104.0),
    ],
)
def test_chart_fixture_rejects_invalid_metadata(field: str, value: object) -> None:
    bars = _bars()
    values: dict[str, object] = {
        "symbol": "TEST_FLAT",
        "pattern_label": "Flat fixture",
        "bars": bars,
        "base_start": bars[90].timestamp_utc,
        "base_end": bars[-1].timestamp_utc,
        "support": 98.0,
        "resistance": 103.0,
    }
    values[field] = value

    with pytest.raises(ValueError):
        ChartFixture(**values)  # type: ignore[arg-type]


def test_chart_fixture_rejects_short_unsorted_or_duplicate_bars() -> None:
    bars = _bars()
    common = {
        "symbol": "TEST_FLAT",
        "pattern_label": "Flat fixture",
        "base_start": bars[90].timestamp_utc,
        "base_end": bars[-1].timestamp_utc,
        "support": 98.0,
        "resistance": 103.0,
    }

    with pytest.raises(ValueError):
        ChartFixture(bars=bars[:119], **common)
    with pytest.raises(ValueError):
        ChartFixture(bars=bars[:-2] + (bars[-1], bars[-2]), **common)
    with pytest.raises(ValueError):
        ChartFixture(bars=bars[:-1] + (bars[-2],), **common)


def test_chart_fixture_rejects_mutable_bar_container() -> None:
    bars = _bars()

    with pytest.raises(ValueError, match="immutable tuple"):
        ChartFixture(
            symbol="TEST_FLAT",
            pattern_label="Flat fixture",
            bars=list(bars),  # type: ignore[arg-type]
            base_start=bars[90].timestamp_utc,
            base_end=bars[-1].timestamp_utc,
            support=98.0,
            resistance=103.0,
        )


def test_phase1_models_have_only_milestone_1_fields() -> None:
    assert {field.name for field in fields(DailyBar)} == {
        "timestamp_utc",
        "open",
        "high",
        "low",
        "close",
        "volume",
    }
    assert {field.name for field in fields(ChartFixture)} == {
        "symbol",
        "pattern_label",
        "bars",
        "base_start",
        "base_end",
        "support",
        "resistance",
    }
