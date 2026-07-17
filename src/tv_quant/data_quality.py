"""Standardization and validation for daily OHLCV data."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


REQUIRED_COLUMNS = ("timestamp_utc", "ticker", "open", "high", "low", "close", "volume")


class DataQualityError(ValueError):
    """Raised when a daily OHLCV file cannot be used for a backtest."""


def validate_ohlcv(data: pd.DataFrame) -> list[str]:
    """Validate standardized data and return non-fatal price-move warnings."""
    if data.empty:
        raise DataQualityError("empty OHLCV data")

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in data.columns]
    if missing_columns:
        raise DataQualityError(f"missing required columns: {', '.join(missing_columns)}")

    timestamps = pd.to_datetime(data["timestamp_utc"], utc=True, errors="coerce")
    if timestamps.isna().any():
        raise DataQualityError("missing or invalid timestamp_utc")
    if timestamps.duplicated().any():
        raise DataQualityError("duplicate timestamp_utc")
    if not timestamps.is_monotonic_increasing:
        raise DataQualityError("timestamp_utc must be strictly sorted")
    if not timestamps.eq(timestamps.dt.normalize()).all():
        raise DataQualityError("timestamp_utc must be UTC midnight for daily bars")

    if data[list(REQUIRED_COLUMNS)].isna().any().any():
        raise DataQualityError("missing OHLCV values")

    prices = data[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce")
    if prices.isna().any().any() or (prices <= 0).any().any():
        raise DataQualityError("OHLC prices must be positive")
    if not np.isfinite(prices.to_numpy(dtype=float)).all():
        raise DataQualityError("OHLC prices must be finite")

    volume = pd.to_numeric(data["volume"], errors="coerce")
    if volume.isna().any() or (volume < 0).any():
        raise DataQualityError("volume must be non-negative")
    if not np.isfinite(volume.to_numpy(dtype=float)).all():
        raise DataQualityError("volume must be finite")

    if (prices["low"] > prices[["open", "close"]].min(axis=1)).any():
        raise DataQualityError("low price is inconsistent with open/close")
    if (prices["high"] < prices[["open", "close"]].max(axis=1)).any():
        raise DataQualityError("high price is inconsistent with open/close")

    close_change = prices["close"].pct_change().abs()
    warnings: list[str] = []
    for position in close_change[close_change > 0.50].index:
        warnings.append(f"close move exceeds 50% at {timestamps.loc[position].isoformat()}")
    return warnings


def load_standardized_csv(path: str | Path) -> tuple[pd.DataFrame, list[str]]:
    """Load a standardized CSV, canonicalize timestamps, and validate it."""
    data = pd.read_csv(path)
    if "timestamp_utc" in data.columns:
        data["timestamp_utc"] = pd.to_datetime(data["timestamp_utc"], utc=True, errors="coerce")
    warnings = validate_ohlcv(data)
    return data, warnings


def merge_standardized_daily(existing: pd.DataFrame | None, incoming: pd.DataFrame) -> pd.DataFrame:
    """Merge incoming bars, retaining incoming values for duplicate daily records."""
    frames = [frame for frame in (existing, incoming) if frame is not None and not frame.empty]
    if not frames:
        raise DataQualityError("empty OHLCV data")
    combined = pd.concat(frames, ignore_index=True)
    combined["timestamp_utc"] = pd.to_datetime(combined["timestamp_utc"], utc=True, errors="coerce")
    combined = combined.drop_duplicates(subset=["timestamp_utc", "ticker"], keep="last")
    combined = combined.sort_values(["timestamp_utc", "ticker"], kind="stable").reset_index(drop=True)
    validate_ohlcv(combined)
    return combined
