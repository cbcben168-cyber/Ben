from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite


def _is_utc(value: datetime) -> bool:
    return value.tzinfo is not None and value.utcoffset() == timedelta(0)


@dataclass(frozen=True, slots=True)
class DailyBar:
    timestamp_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    def __post_init__(self) -> None:
        if not _is_utc(self.timestamp_utc):
            raise ValueError("timestamp_utc must be timezone-aware UTC")

        prices = (self.open, self.high, self.low, self.close)
        if any(not isfinite(value) or value <= 0 for value in prices):
            raise ValueError("OHLC prices must be positive and finite")
        if self.high < max(self.open, self.close):
            raise ValueError("high must contain open and close")
        if self.low > min(self.open, self.close):
            raise ValueError("low must contain open and close")
        if not isinstance(self.volume, int) or isinstance(self.volume, bool) or self.volume < 0:
            raise ValueError("volume must be a non-negative integer")


@dataclass(frozen=True, slots=True)
class ChartFixture:
    symbol: str
    pattern_label: str
    bars: tuple[DailyBar, ...]
    base_start: datetime
    base_end: datetime
    support: float
    resistance: float

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be non-empty uppercase text")
        if not self.pattern_label.strip():
            raise ValueError("pattern_label must be non-empty")
        if len(self.bars) < 120 or not all(isinstance(bar, DailyBar) for bar in self.bars):
            raise ValueError("bars must contain at least 120 DailyBar values")

        timestamps = tuple(bar.timestamp_utc for bar in self.bars)
        if any(left >= right for left, right in zip(timestamps, timestamps[1:])):
            raise ValueError("bars must be strictly sorted without duplicate timestamps")
        if self.base_start not in timestamps or self.base_end not in timestamps:
            raise ValueError("base window must use bar timestamps")
        if self.base_start > self.base_end:
            raise ValueError("base_start must not follow base_end")
        if (
            not isfinite(self.support)
            or not isfinite(self.resistance)
            or self.support <= 0
            or self.support >= self.resistance
        ):
            raise ValueError("support and resistance must be positive and ordered")
