from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite

import pandas as pd

from tv_quant.data_quality import validate_ohlcv


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
        if not isinstance(self.bars, tuple):
            raise ValueError("bars must use an immutable tuple")
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


@dataclass(frozen=True, slots=True)
class ChartSeries:
    symbol: str
    label: str
    bars: tuple[DailyBar, ...]

    def __post_init__(self) -> None:
        if not self.symbol or self.symbol != self.symbol.strip().upper():
            raise ValueError("symbol must be non-empty uppercase text")
        if not self.label.strip():
            raise ValueError("label must be non-empty")
        if not isinstance(self.bars, tuple) or not self.bars:
            raise ValueError("bars must use a non-empty immutable tuple")
        if not all(isinstance(bar, DailyBar) for bar in self.bars):
            raise ValueError("bars must contain DailyBar values")
        timestamps = tuple(bar.timestamp_utc for bar in self.bars)
        if any(left >= right for left, right in zip(timestamps, timestamps[1:])):
            raise ValueError("bars must be strictly sorted without duplicate timestamps")


def ohlcv_frame_from_series(series: ChartFixture | ChartSeries) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp_utc": [bar.timestamp_utc for bar in series.bars],
            "ticker": [series.symbol] * len(series.bars),
            "open": [bar.open for bar in series.bars],
            "high": [bar.high for bar in series.bars],
            "low": [bar.low for bar in series.bars],
            "close": [bar.close for bar in series.bars],
            "volume": [bar.volume for bar in series.bars],
        }
    )


def chart_series_from_frame(
    data: pd.DataFrame,
    symbol: str,
    *,
    max_bars: int = 150,
) -> ChartSeries:
    if max_bars <= 0:
        raise ValueError("max_bars must be positive")
    validate_ohlcv(data)
    normalized_symbol = symbol.strip().upper()
    tickers = set(data["ticker"].astype(str).str.strip().str.upper())
    if tickers != {normalized_symbol}:
        raise ValueError(
            f"symbol mismatch: expected {normalized_symbol}, got {sorted(tickers)}"
        )

    recent = data.tail(max_bars)
    bars: list[DailyBar] = []
    for row in recent.itertuples(index=False):
        volume = float(row.volume)
        if not volume.is_integer():
            raise ValueError("volume must be a whole number for chart bars")
        timestamp = pd.Timestamp(row.timestamp_utc).tz_convert("UTC").to_pydatetime()
        bars.append(
            DailyBar(
                timestamp_utc=timestamp,
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
                volume=int(volume),
            )
        )
    return ChartSeries(
        symbol=normalized_symbol,
        label="Futu QFQ daily",
        bars=tuple(bars),
    )
