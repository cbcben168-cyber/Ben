"""Futu OpenD quote-only daily download and safe CSV updates."""
from __future__ import annotations
import os, tempfile, time
from collections.abc import Set as AbstractSet
from datetime import date
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Protocol
import pandas as pd
from .data_quality import load_standardized_csv, merge_standardized_daily, validate_ohlcv

class FutuDownloadError(RuntimeError): pass
@dataclass(frozen=True)
class FutuCsvUpdate:
    path: Path
    new_rows: int
    updated_rows: int
    total_rows: int
class QuoteContext(Protocol):
    def request_history_kline(self, **kwargs: Any) -> tuple[int, pd.DataFrame | str, bytes | None]: ...

_DEFAULT_ALLOWED_TICKERS = frozenset({"SPY", "QQQ"})


def futu_to_standardized(
    data: pd.DataFrame,
    *,
    allowed_tickers: AbstractSet[str] | None = None,
) -> pd.DataFrame:
    required = {"code", "time_key", "open", "high", "low", "close", "volume"}
    if missing := required.difference(data.columns): raise FutuDownloadError(f"Futu data missing columns: {', '.join(sorted(missing))}")
    dates = pd.to_datetime(data["time_key"], errors="coerce").dt.date
    result = pd.DataFrame({"timestamp_utc": pd.to_datetime(dates, utc=True), "ticker": data["code"].astype(str).str.removeprefix("US."), "open": data["open"], "high": data["high"], "low": data["low"], "close": data["close"], "volume": data["volume"]})
    tickers = set(result["ticker"].astype(str).str.upper())
    allowed = _DEFAULT_ALLOWED_TICKERS if allowed_tickers is None else {
        str(ticker).upper() for ticker in allowed_tickers
    }
    if len(tickers) != 1 or not tickers.issubset(allowed):
        raise FutuDownloadError(f"Futu data must contain exactly one supported ticker, got {sorted(tickers)}")
    validate_ohlcv(result); return result

def download_futu_daily(code: str, start: date, end: date, quote_context: QuoteContext, *, ret_ok: int = 0, ktype: Any = "K_DAY", autype: Any = "QFQ", allowed_tickers: AbstractSet[str] | None = None, sleep: Callable[[float], None] = time.sleep) -> pd.DataFrame:
    pages: list[pd.DataFrame] = []; page_key = None
    while True:
        sleep(1)
        ret, data, next_key = quote_context.request_history_kline(code=code, start=start.isoformat(), end=end.isoformat(), ktype=ktype, autype=autype, max_count=1000, page_req_key=page_key)
        if ret != ret_ok: raise FutuDownloadError(f"Futu history request failed for {code}: {data}")
        if not isinstance(data, pd.DataFrame): raise FutuDownloadError(f"Futu history request returned invalid data for {code}")
        pages.append(data)
        if next_key is None: break
        page_key = next_key
    result = futu_to_standardized(
        pd.concat(pages, ignore_index=True),
        allowed_tickers=allowed_tickers,
    )
    expected_ticker = code.removeprefix("US.").upper()
    if set(result["ticker"].astype(str).str.upper()) != {expected_ticker}:
        raise FutuDownloadError(f"Futu returned ticker other than requested {code}")
    return result

def update_futu_csv(destination: str | Path, code: str, start: date, end: date, quote_context: QuoteContext, *, ret_ok: int = 0, ktype: Any = "K_DAY", autype: Any = "QFQ", allowed_tickers: AbstractSet[str] | None = None, sleep: Callable[[float], None] = time.sleep, before_replace: Callable[[pd.DataFrame], None] | None = None) -> FutuCsvUpdate:
    destination = Path(destination); incoming = download_futu_daily(code, start, end, quote_context, ret_ok=ret_ok, ktype=ktype, autype=autype, allowed_tickers=allowed_tickers, sleep=sleep)
    existing = load_standardized_csv(destination)[0] if destination.exists() else None
    existing_keys = set() if existing is None else set(zip(existing["ticker"], existing["timestamp_utc"]))
    incoming_keys = set(zip(incoming["ticker"], incoming["timestamp_utc"]))
    merged = merge_standardized_daily(existing, incoming)
    if before_replace is not None:
        before_replace(merged)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".csv", dir=destination.parent, delete=False, encoding="utf-8", newline="") as handle:
        temporary = Path(handle.name); merged.to_csv(handle, index=False, date_format="%Y-%m-%dT%H:%M:%SZ")
    try: os.replace(temporary, destination)
    except Exception: temporary.unlink(missing_ok=True); raise
    return FutuCsvUpdate(destination, len(incoming_keys - existing_keys), len(incoming_keys & existing_keys), len(merged))
