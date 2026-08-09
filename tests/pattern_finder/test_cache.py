from datetime import UTC, datetime, timedelta
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
import pytest

from tv_quant.pattern_finder.cache import (
    DEFAULT_CACHE_ROOT,
    PatternCacheError,
    cache_path,
    cache_status_rows,
    refresh_cache_entry,
)
from tv_quant.pattern_finder.universe import PILOT_SYMBOLS


class Context:
    def __init__(self, frame: pd.DataFrame):
        self.frame = frame
        self.requests: list[dict[str, object]] = []

    def request_history_kline(self, **kwargs):
        self.requests.append(kwargs)
        return 0, self.frame.copy(), None


def _raw_frame(symbol: str, days: list[str], closes: list[float] | None = None) -> pd.DataFrame:
    close_values = closes or [100.5 + index for index in range(len(days))]
    return pd.DataFrame(
        {
            "code": [f"US.{symbol}"] * len(days),
            "name": [symbol] * len(days),
            "time_key": [f"{day} 00:00:00" for day in days],
            "open": [value - 0.5 for value in close_values],
            "high": [value + 0.5 for value in close_values],
            "low": [value - 1.0 for value in close_values],
            "close": close_values,
            "volume": [1_000_000 + index for index in range(len(days))],
        }
    )


def _standard_frame(symbol: str, days: list[str], closes: list[float] | None = None) -> pd.DataFrame:
    raw = _raw_frame(symbol, days, closes)
    return pd.DataFrame(
        {
            "timestamp_utc": pd.to_datetime(days, utc=True),
            "ticker": symbol,
            "open": raw["open"],
            "high": raw["high"],
            "low": raw["low"],
            "close": raw["close"],
            "volume": raw["volume"],
        }
    )


def _xnys_days(start: str, end: str) -> list[str]:
    sessions = xcals.get_calendar("XNYS").sessions_in_range(start, end)
    return [session.date().isoformat() for session in sessions]


def test_cache_path_is_qfq_scoped_and_per_symbol(tmp_path: Path) -> None:
    assert DEFAULT_CACHE_ROOT == Path("data/raw/pattern_finder/qfq")
    assert cache_path(tmp_path, "aapl") == tmp_path / "AAPL_daily.csv"


def test_first_refresh_requests_qfq_daily_history_through_latest_complete_session(tmp_path: Path) -> None:
    as_of = datetime(2026, 7, 6, 20, 1, tzinfo=UTC)
    end = as_of.date()
    start = end - timedelta(days=550)
    days = _xnys_days(start.isoformat(), end.isoformat())
    context = Context(_raw_frame("AAPL", days))

    entry = refresh_cache_entry(
        "AAPL",
        context,
        cache_root=tmp_path,
        as_of_utc=as_of,
        ret_ok=0,
        ktype="K_DAY_VALUE",
        autype="QFQ_VALUE",
        sleep=lambda _: None,
    )

    request = context.requests[0]
    assert request["start"] == start.isoformat()
    assert request["end"] == "2026-07-06"
    assert request["ktype"] == "K_DAY_VALUE"
    assert request["autype"] == "QFQ_VALUE"
    assert entry.symbol == "AAPL"
    assert entry.quality.passed is True
    assert entry.rows == len(days)


def test_incremental_refresh_overlaps_and_replaces_corrected_session(tmp_path: Path) -> None:
    target = cache_path(tmp_path, "AAPL")
    target.parent.mkdir(parents=True, exist_ok=True)
    _standard_frame(
        "AAPL",
        ["2026-07-01", "2026-07-02", "2026-07-06"],
        [100.5, 101.5, 102.5],
    ).to_csv(target, index=False)
    context = Context(
        _raw_frame("AAPL", ["2026-07-06", "2026-07-07"], [103.5, 104.5])
    )

    entry = refresh_cache_entry(
        "AAPL",
        context,
        cache_root=tmp_path,
        as_of_utc=datetime(2026, 7, 7, 20, 1, tzinfo=UTC),
        sleep=lambda _: None,
    )

    assert context.requests[0]["start"] == "2026-06-26"
    assert (entry.new_rows, entry.updated_rows, entry.rows) == (1, 1, 4)
    assert pd.read_csv(target)["close"].tolist() == [100.5, 101.5, 103.5, 104.5]


def test_quality_failure_preserves_existing_cache(tmp_path: Path) -> None:
    target = cache_path(tmp_path, "AAPL")
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = _standard_frame("AAPL", ["2026-07-01", "2026-07-06"])
    existing.to_csv(target, index=False)
    before = target.read_bytes()
    context = Context(_raw_frame("AAPL", ["2026-07-07"]))

    with pytest.raises(PatternCacheError, match="missing XNYS sessions"):
        refresh_cache_entry(
            "AAPL",
            context,
            cache_root=tmp_path,
            as_of_utc=datetime(2026, 7, 7, 20, 1, tzinfo=UTC),
            sleep=lambda _: None,
        )

    assert target.read_bytes() == before


def test_cache_status_reports_missing_pass_and_stale_without_network(tmp_path: Path) -> None:
    for symbol, days in (
        ("AAPL", ["2026-07-01", "2026-07-02", "2026-07-06"]),
        ("MSFT", ["2026-07-01", "2026-07-02"]),
    ):
        target = cache_path(tmp_path, symbol)
        target.parent.mkdir(parents=True, exist_ok=True)
        _standard_frame(symbol, days).to_csv(target, index=False)

    rows = cache_status_rows(
        tmp_path,
        datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
    )
    by_symbol = {row["Symbol"]: row for row in rows}

    assert tuple(by_symbol) == PILOT_SYMBOLS
    assert by_symbol["AAPL"]["Data Quality"] == "PASS"
    assert by_symbol["MSFT"]["Data Quality"] == "FAIL"
    assert by_symbol["NVDA"]["Cache"] == "Missing"
    assert by_symbol["AAPL"]["Adjustment"] == "QFQ"
