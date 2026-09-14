from datetime import UTC, datetime
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd
import pytest

from tv_quant.futu_quota import QuotaPolicyError
from tv_quant.pattern_finder import futu_service
from tv_quant.pattern_finder.cache import PatternCacheError
from tv_quant.pattern_finder.futu_service import (
    refresh_pilot_universe,
    refresh_symbols,
    refresh_universe_to_target,
    stale_cached_symbols,
)
from tv_quant.pattern_finder.universe import PILOT_SYMBOLS


class Context:
    def __init__(
        self,
        *,
        ready: bool = True,
        remain_quota: int = 120,
        failing_codes: frozenset[str] = frozenset(),
    ):
        self.ready = ready
        self.remain_quota = remain_quota
        self.failing_codes = failing_codes
        self.known_codes: list[str] = []
        self.requests: list[dict[str, object]] = []
        self.closed = False

    def get_global_state(self):
        return 0, {
            "qot_logined": True,
            "program_status_type": "READY" if self.ready else "STARTING",
        }

    def get_history_kl_quota(self, *, get_detail: bool):
        assert get_detail is True
        return 0, (
            len(self.known_codes),
            self.remain_quota,
            [{"code": code} for code in self.known_codes],
        )

    def request_history_kline(self, **kwargs):
        self.requests.append(kwargs)
        code = str(kwargs["code"])
        if code in self.failing_codes:
            return 1, "provider timeout", None
        if code not in self.known_codes:
            self.known_codes.append(code)
            self.remain_quota -= 1
        days = [
            session.date().isoformat()
            for session in xcals.get_calendar("XNYS").sessions_in_range(
                kwargs["start"], kwargs["end"]
            )
        ]
        symbol = str(kwargs["code"]).removeprefix("US.")
        frame = pd.DataFrame(
            {
                "code": [f"US.{symbol}"] * len(days),
                "name": [symbol] * len(days),
                "time_key": [f"{day} 00:00:00" for day in days],
                "open": [100.0] * len(days),
                "high": [102.0] * len(days),
                "low": [99.0] * len(days),
                "close": [101.0] * len(days),
                "volume": [1_000_000] * len(days),
            }
        )
        return 0, frame, None

    def close(self) -> None:
        self.closed = True


class Sdk:
    RET_OK = 0

    class AuType:
        QFQ = "REAL_QFQ"

    class KLType:
        K_DAY = "REAL_K_DAY"

    class ProgramStatusType:
        READY = "READY"

    def __init__(self, context: Context):
        self.context = context
        self.connection_args: tuple[str, int] | None = None

    def OpenQuoteContext(self, *, host: str, port: int) -> Context:
        self.connection_args = (host, port)
        return self.context


def test_refreshes_exact_pilot_with_qfq_daily_and_closes_context(tmp_path: Path) -> None:
    context = Context()
    sdk = Sdk(context)

    entries = refresh_pilot_universe(
        cache_root=tmp_path / "cache",
        as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
        log_path=tmp_path / "quota.jsonl",
        sdk=sdk,
        sleep=lambda _: None,
    )

    assert tuple(entry.symbol for entry in entries) == PILOT_SYMBOLS
    assert tuple(request["code"] for request in context.requests) == tuple(
        f"US.{symbol}" for symbol in PILOT_SYMBOLS
    )
    assert {request["ktype"] for request in context.requests} == {"REAL_K_DAY"}
    assert {request["autype"] for request in context.requests} == {"REAL_QFQ"}
    assert sdk.connection_args == ("127.0.0.1", 11111)
    assert context.closed is True


def test_unavailable_opend_is_explicit_and_context_is_closed(tmp_path: Path) -> None:
    context = Context(ready=False)

    with pytest.raises(RuntimeError, match="OpenD.*登录"):
        refresh_pilot_universe(
            cache_root=tmp_path / "cache",
            as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
            log_path=tmp_path / "quota.jsonl",
            sdk=Sdk(context),
            sleep=lambda _: None,
        )

    assert context.requests == []
    assert context.closed is True


def test_quota_policy_failure_stops_before_download_and_closes_context(tmp_path: Path) -> None:
    context = Context(remain_quota=0)

    with pytest.raises(QuotaPolicyError, match="no remaining"):
        refresh_pilot_universe(
            cache_root=tmp_path / "cache",
            as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
            log_path=tmp_path / "quota.jsonl",
            sdk=Sdk(context),
            sleep=lambda _: None,
        )

    assert context.requests == []
    assert context.closed is True


def test_refresh_symbols_preserves_exact_order_and_uses_provider_quota(tmp_path: Path) -> None:
    context = Context(remain_quota=2)

    entries = refresh_symbols(
        ("BAC", "WFC"),
        cache_root=tmp_path / "cache",
        as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
        log_path=tmp_path / "quota.jsonl",
        sdk=Sdk(context),
        sleep=lambda _: None,
    )

    assert tuple(entry.symbol for entry in entries) == ("BAC", "WFC")
    assert tuple(request["code"] for request in context.requests) == (
        "US.BAC",
        "US.WFC",
    )
    assert context.remain_quota == 0
    assert context.closed is True


def test_refresh_symbols_isolates_middle_failure_and_returns_ordered_summary(
    tmp_path: Path,
) -> None:
    context = Context(
        remain_quota=4,
        failing_codes=frozenset({"US.AMZN"}),
    )

    result = refresh_symbols(
        ("AAPL", "MSFT", "AMZN", "GOOGL"),
        cache_root=tmp_path / "cache",
        as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
        log_path=tmp_path / "quota.jsonl",
        sdk=Sdk(context),
        sleep=lambda _: None,
    )

    assert tuple(request["code"] for request in context.requests) == (
        "US.AAPL",
        "US.MSFT",
        "US.AMZN",
        "US.AMZN",
        "US.GOOGL",
    )
    assert tuple(outcome.symbol for outcome in result.outcomes) == (
        "AAPL",
        "MSFT",
        "AMZN",
        "GOOGL",
    )
    assert tuple(entry.symbol for entry in result.successes) == (
        "AAPL",
        "MSFT",
        "GOOGL",
    )
    assert len(result.failures) == 1
    assert result.failures[0].symbol == "AMZN"
    assert result.failures[0].error_type == "FutuDownloadError"
    assert result.failures[0].message == (
        "Futu history request failed for US.AMZN: provider timeout"
    )
    assert context.closed is True


def test_refresh_symbols_records_pattern_cache_error_once_and_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context(remain_quota=3)
    original_refresh = futu_service.refresh_cache_entry
    refresh_calls: list[str] = []

    def refresh_with_cache_failure(symbol: str, *args, **kwargs):
        refresh_calls.append(symbol)
        if symbol == "AMZN":
            raise PatternCacheError("quality gate failed")
        return original_refresh(symbol, *args, **kwargs)

    monkeypatch.setattr(futu_service, "refresh_cache_entry", refresh_with_cache_failure)

    result = refresh_symbols(
        ("AAPL", "AMZN", "GOOGL"),
        cache_root=tmp_path / "cache",
        as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
        log_path=tmp_path / "quota.jsonl",
        sdk=Sdk(context),
        sleep=lambda _: None,
    )

    assert refresh_calls == ["AAPL", "AMZN", "GOOGL"]
    assert tuple(request["code"] for request in context.requests) == (
        "US.AAPL",
        "US.GOOGL",
    )
    assert tuple(entry.symbol for entry in result.successes) == ("AAPL", "GOOGL")
    assert tuple(failure.symbol for failure in result.failures) == ("AMZN",)
    assert result.failures[0].error_type == "PatternCacheError"
    assert context.closed is True


def test_refresh_symbols_keeps_unexpected_exception_fail_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = Context(remain_quota=3)
    original_refresh = futu_service.refresh_cache_entry
    refresh_calls: list[str] = []

    def refresh_with_programmer_error(symbol: str, *args, **kwargs):
        refresh_calls.append(symbol)
        if symbol == "AMZN":
            raise AssertionError("programmer bug")
        return original_refresh(symbol, *args, **kwargs)

    monkeypatch.setattr(futu_service, "refresh_cache_entry", refresh_with_programmer_error)

    with pytest.raises(AssertionError, match="programmer bug"):
        refresh_symbols(
            ("AAPL", "AMZN", "GOOGL"),
            cache_root=tmp_path / "cache",
            as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
            log_path=tmp_path / "quota.jsonl",
            sdk=Sdk(context),
            sleep=lambda _: None,
        )

    assert refresh_calls == ["AAPL", "AMZN"]
    assert tuple(request["code"] for request in context.requests) == ("US.AAPL",)
    assert context.closed is True


@pytest.mark.parametrize(
    (
        "failing_codes",
        "expected_requests",
        "expected_successes",
        "expected_failures",
    ),
    (
        (
            frozenset({"US.AAPL"}),
            ("US.AAPL", "US.AAPL", "US.MSFT", "US.AMZN", "US.GOOGL"),
            ("MSFT", "AMZN", "GOOGL"),
            ("AAPL",),
        ),
        (
            frozenset({"US.AAPL", "US.AMZN"}),
            (
                "US.AAPL",
                "US.AAPL",
                "US.MSFT",
                "US.AMZN",
                "US.AMZN",
                "US.GOOGL",
            ),
            ("MSFT", "GOOGL"),
            ("AAPL", "AMZN"),
        ),
    ),
)
def test_refresh_symbols_preserves_later_successes_for_first_and_multiple_failures(
    tmp_path: Path,
    failing_codes: frozenset[str],
    expected_requests: tuple[str, ...],
    expected_successes: tuple[str, ...],
    expected_failures: tuple[str, ...],
) -> None:
    symbols = ("AAPL", "MSFT", "AMZN", "GOOGL")
    context = Context(remain_quota=4, failing_codes=failing_codes)

    result = refresh_symbols(
        symbols,
        cache_root=tmp_path / "cache",
        as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
        log_path=tmp_path / "quota.jsonl",
        sdk=Sdk(context),
        sleep=lambda _: None,
    )

    assert tuple(request["code"] for request in context.requests) == expected_requests
    assert tuple(outcome.symbol for outcome in result.outcomes) == symbols
    assert tuple(entry.symbol for entry in result.successes) == expected_successes
    assert tuple(failure.symbol for failure in result.failures) == expected_failures
    assert context.closed is True


def test_refresh_symbols_blocks_new_code_at_zero_and_closes_context(tmp_path: Path) -> None:
    context = Context(remain_quota=0)

    with pytest.raises(QuotaPolicyError, match="no remaining"):
        refresh_symbols(
            ("BAC",),
            cache_root=tmp_path / "cache",
            as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
            log_path=tmp_path / "quota.jsonl",
            sdk=Sdk(context),
            sleep=lambda _: None,
        )

    assert context.requests == []
    assert context.closed is True


def test_stale_cached_symbols_returns_only_failed_quality_in_cache_order(
    tmp_path: Path,
) -> None:
    for symbol, end in (("BAC", "2026-07-01"), ("WFC", "2026-07-06")):
        sessions = xcals.get_calendar("XNYS").sessions_window(end, -379)
        pd.DataFrame(
            {
                "timestamp_utc": sessions,
                "ticker": symbol,
                "open": 100.0,
                "high": 102.0,
                "low": 99.0,
                "close": 101.0,
                "volume": 1_000_000,
            }
        ).to_csv(tmp_path / f"{symbol}_daily.csv", index=False)

    assert stale_cached_symbols(
        cache_root=tmp_path,
        as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
    ) == ("BAC",)


def test_expansion_rejects_non_milestone_target_before_connecting(tmp_path: Path) -> None:
    context = Context()

    with pytest.raises(ValueError, match="25, 50, or 100"):
        refresh_universe_to_target(
            40,
            cache_root=tmp_path / "cache",
            as_of_utc=datetime(2026, 7, 6, 20, 1, tzinfo=UTC),
            log_path=tmp_path / "quota.jsonl",
            sdk=Sdk(context),
            sleep=lambda _: None,
        )

    assert context.requests == []
    assert context.closed is False
