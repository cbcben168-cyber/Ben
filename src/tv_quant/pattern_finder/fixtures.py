from __future__ import annotations

from math import sin

import pandas as pd

from .models import ChartFixture, DailyBar


def _close_for(symbol: str, index: int) -> float:
    if symbol == "TEST_FLAT":
        return 110.0 - 0.12 * index if index < 100 else 98.0 + 0.65 * sin(index / 3)
    if symbol == "TEST_ROUNDED":
        return 110.0 - 0.15 * index if index < 100 else 90.0 + ((index - 130) ** 2) / 225
    return 115.0 - 0.10 * index if index < 100 else 100.0 + 0.075 * (index - 100) + 0.25 * sin(index / 3)


def _volume_for(symbol: str, index: int) -> int:
    if symbol == "TEST_FLAT":
        return 1_200_000 + (index % 11) * 15_000
    if symbol == "TEST_ROUNDED":
        return 1_500_000 - index * 2_000 + (index % 7) * 10_000
    return max(600_000, 2_000_000 - index * 8_000 + (index % 5) * 12_000)


def _build_fixture(
    symbol: str,
    pattern_label: str,
    support: float,
    resistance: float,
) -> ChartFixture:
    timestamps = pd.bdate_range(end="2026-08-07", periods=160, tz="UTC").to_pydatetime()
    bars: list[DailyBar] = []
    for index, timestamp in enumerate(timestamps):
        close = round(_close_for(symbol, index), 4)
        open_price = round(close + ((index % 3) - 1) * 0.15, 4)
        bars.append(
            DailyBar(
                timestamp_utc=timestamp,
                open=open_price,
                high=round(max(open_price, close) + 0.8, 4),
                low=round(min(open_price, close) - 0.8, 4),
                close=close,
                volume=_volume_for(symbol, index),
            )
        )

    frozen_bars = tuple(bars)
    return ChartFixture(
        symbol=symbol,
        pattern_label=pattern_label,
        bars=frozen_bars,
        base_start=frozen_bars[100].timestamp_utc,
        base_end=frozen_bars[-1].timestamp_utc,
        support=support,
        resistance=resistance,
    )


_FIXTURES = (
    _build_fixture("TEST_FLAT", "Flat fixture", 96.5, 100.0),
    _build_fixture("TEST_ROUNDED", "Rounded fixture", 89.0, 95.0),
    _build_fixture("TEST_READY", "Ready fixture", 99.0, 105.5),
)


def load_fixtures() -> tuple[ChartFixture, ...]:
    return _FIXTURES


def load_fixture(symbol: str) -> ChartFixture:
    for fixture in _FIXTURES:
        if fixture.symbol == symbol:
            return fixture
    raise ValueError(f"unknown fixture symbol: {symbol}")
