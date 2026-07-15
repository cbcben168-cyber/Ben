"""Daily data download for the first-phase supported ETFs."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from .data_quality import validate_ohlcv


SUPPORTED_TICKERS = ("SPY", "QQQ")


def default_date_range(years: int) -> tuple[date, date]:
    end = date.today()
    return end - timedelta(days=365 * years), end


def download_daily(ticker: str, start: date, end: date) -> pd.DataFrame:
    """Return fully adjusted daily bars in the project's standardized schema."""
    ticker = ticker.upper()
    if ticker not in SUPPORTED_TICKERS:
        raise ValueError(f"unsupported ticker: {ticker}")

    history = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=True,
        actions=False,
    )
    if history.empty:
        raise ValueError(f"no daily data returned for {ticker}")

    index = pd.DatetimeIndex(history.index)
    if index.tz is None:
        timestamps = index.tz_localize("UTC").normalize()
    else:
        timestamps = index.tz_convert("UTC").normalize()
    data = pd.DataFrame(
        {
            "timestamp_utc": timestamps,
            "ticker": ticker,
            "open": history["Open"].to_numpy(),
            "high": history["High"].to_numpy(),
            "low": history["Low"].to_numpy(),
            "close": history["Close"].to_numpy(),
            "volume": history["Volume"].to_numpy(),
        }
    )
    validate_ohlcv(data)
    return data


def save_daily_csv(data: pd.DataFrame, output_dir: str | Path, overwrite: bool = False) -> Path:
    """Save a single standardized ticker CSV without accidental replacement."""
    ticker = str(data["ticker"].iloc[0]).upper()
    destination = Path(output_dir) / f"{ticker}_daily.csv"
    if destination.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {destination}; use --overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    data.to_csv(destination, index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
    return destination
