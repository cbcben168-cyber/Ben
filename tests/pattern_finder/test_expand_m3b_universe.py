import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import exchange_calendars as xcals
import pandas as pd

from scripts.expand_m3b_universe import main
from tv_quant.pattern_finder.data_quality import latest_complete_xnys_session
from tv_quant.pattern_finder.futu_service import (
    ExpansionResult,
    refresh_universe_to_target,
)
from tv_quant.pattern_finder.universe import M3B_SYMBOLS, PILOT_SYMBOLS


AS_OF = datetime.now(UTC).replace(second=0, microsecond=0)


def _sessions(as_of: datetime) -> list[str]:
    end = latest_complete_xnys_session(as_of)
    start = end - timedelta(days=550)
    return [
        session.date().isoformat()
        for session in xcals.get_calendar("XNYS").sessions_in_range(start, end)
    ]


def _seed_valid_cache(root: Path, symbols: tuple[str, ...], as_of: datetime) -> None:
    days = _sessions(as_of)
    root.mkdir(parents=True, exist_ok=True)
    for symbol in symbols:
        pd.DataFrame(
            {
                "timestamp_utc": [pd.Timestamp(day, tz="UTC") for day in days],
                "ticker": [symbol] * len(days),
                "open": [100.0] * len(days),
                "high": [102.0] * len(days),
                "low": [99.0] * len(days),
                "close": [101.0] * len(days),
                "volume": [1_000_000] * len(days),
            }
        ).to_csv(root / f"{symbol}_daily.csv", index=False)


class ExpansionContext:
    def __init__(
        self,
        known: tuple[str, ...],
        *,
        remain_quota: int = 292,
        ready: bool = True,
    ) -> None:
        self.known = {f"US.{symbol}" for symbol in known}
        self.used_quota = len(self.known)
        self.remain_quota = remain_quota
        self.ready = ready
        self.requests: list[dict[str, object]] = []
        self.closed = False

    def get_global_state(self):
        return 0, {
            "qot_logined": True,
            "program_status_type": "READY" if self.ready else "STARTING",
        }

    def get_history_kl_quota(self, *, get_detail: bool):
        assert get_detail is True
        details = [{"code": code} for code in sorted(self.known)]
        return 0, (self.used_quota, self.remain_quota, details)

    def request_history_kline(self, **kwargs):
        self.requests.append(kwargs)
        code = str(kwargs["code"])
        if code not in self.known:
            self.known.add(code)
            self.used_quota += 1
            self.remain_quota -= 1
        days = [
            session.date().isoformat()
            for session in xcals.get_calendar("XNYS").sessions_in_range(
                kwargs["start"], kwargs["end"]
            )
        ]
        symbol = code.removeprefix("US.")
        frame = pd.DataFrame(
            {
                "code": [code] * len(days),
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


class ExpansionSdk:
    RET_OK = 0

    class AuType:
        QFQ = "REAL_QFQ"

    class KLType:
        K_DAY = "REAL_K_DAY"

    class ProgramStatusType:
        READY = "READY"

    def __init__(self, context: ExpansionContext) -> None:
        self.context = context

    def OpenQuoteContext(self, *, host: str, port: int) -> ExpansionContext:
        assert (host, port) == ("127.0.0.1", 11111)
        return self.context


def test_expansion_downloads_only_missing_symbols_until_total_target(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    _seed_valid_cache(cache_root, PILOT_SYMBOLS, AS_OF)
    context = ExpansionContext(PILOT_SYMBOLS)

    result = refresh_universe_to_target(
        25,
        cache_root=cache_root,
        as_of_utc=AS_OF,
        log_path=tmp_path / "quota.jsonl",
        sdk=ExpansionSdk(context),
        sleep=lambda _: None,
    )

    expected = tuple(symbol for symbol in M3B_SYMBOLS if symbol not in PILOT_SYMBOLS)[:17]
    assert result.starting_count == 8
    assert result.completed_symbols == expected
    assert result.final_count == 25
    assert result.blocker is None
    assert result.starting_quota.remain_quota == 292
    assert result.ending_quota.remain_quota == 275
    assert tuple(request["code"] for request in context.requests) == tuple(
        f"US.{symbol}" for symbol in expected
    )
    assert context.closed is True


def test_expansion_stops_when_provider_new_code_quota_reaches_zero(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    log_path = tmp_path / "quota.jsonl"
    _seed_valid_cache(cache_root, PILOT_SYMBOLS, AS_OF)
    context = ExpansionContext(PILOT_SYMBOLS, remain_quota=1)

    result = refresh_universe_to_target(
        25,
        cache_root=cache_root,
        as_of_utc=AS_OF,
        log_path=log_path,
        sdk=ExpansionSdk(context),
        sleep=lambda _: None,
    )

    assert len(result.completed_symbols) == 1
    assert result.final_count == 9
    assert result.blocker is not None
    assert result.blocker.startswith("FUTU_QUOTA_BLOCKER")
    assert context.closed is True


def test_expansion_allows_positive_provider_quota_below_legacy_floor(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    _seed_valid_cache(cache_root, PILOT_SYMBOLS, AS_OF)
    context = ExpansionContext(PILOT_SYMBOLS, remain_quota=99)

    result = refresh_universe_to_target(
        25,
        cache_root=cache_root,
        as_of_utc=AS_OF,
        log_path=tmp_path / "quota.jsonl",
        sdk=ExpansionSdk(context),
        sleep=lambda _: None,
    )

    expected = tuple(symbol for symbol in M3B_SYMBOLS if symbol not in PILOT_SYMBOLS)[:17]
    assert result.completed_symbols == expected
    assert result.final_count == 25
    assert result.blocker is None
    assert result.ending_quota is not None
    assert result.ending_quota.remain_quota == 82
    assert tuple(request["code"] for request in context.requests) == tuple(
        f"US.{symbol}" for symbol in expected
    )
    assert context.closed is True


def test_cli_prints_machine_readable_summary(capsys, tmp_path: Path) -> None:
    def service(target_size: int, **kwargs) -> ExpansionResult:
        context = ExpansionContext(())
        _, quota_data = context.get_history_kl_quota(get_detail=True)
        from tv_quant.futu_quota import QuotaSnapshot

        quota = QuotaSnapshot(quota_data[0], quota_data[1], quota_data[2])
        return ExpansionResult(
            target_size=target_size,
            starting_count=8,
            completed_symbols=tuple(M3B_SYMBOLS[8:25]),
            final_count=25,
            starting_quota=quota,
            ending_quota=quota,
            blocker=None,
        )

    exit_code = main(
        ["--target-size", "25", "--cache-root", str(tmp_path)],
        service=service,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["target_size"] == 25
    assert payload["final_count"] == 25
    assert payload["blocker"] is None
