from datetime import date
from typing import Any

import pandas as pd
import pytest

from tv_quant.futu_downloader import FutuDownloadError, download_futu_daily


class Context:
    def __init__(self, responses: list[tuple[int, Any, bytes | None]]) -> None:
        self.responses = iter(responses)
        self.page_keys: list[bytes | None] = []

    def request_history_kline(self, **kwargs: Any):
        self.page_keys.append(kwargs["page_req_key"])
        return next(self.responses)


def page(day: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": ["US.SPY"],
            "time_key": [f"{day} 00:00:00"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1_000],
        }
    )


@pytest.mark.parametrize("detail", ("provider timeout", "获取历史K线超时"))
def test_transient_history_timeout_retries_once_then_succeeds(detail: str) -> None:
    context = Context([(1, detail, None), (0, page("2024-01-02"), None)])
    sleeps: list[float] = []

    data = download_futu_daily(
        "US.SPY",
        date(2024, 1, 1),
        date(2024, 1, 2),
        context,
        sleep=sleeps.append,
    )

    assert context.page_keys == [None, None]
    assert sleeps == [1, 1]
    assert data["ticker"].tolist() == ["SPY"]


def test_non_timeout_history_error_is_not_retried() -> None:
    context = Context(
        [(1, "permission denied", None), (0, page("2024-01-02"), None)]
    )

    with pytest.raises(FutuDownloadError, match="permission denied"):
        download_futu_daily(
            "US.SPY",
            date(2024, 1, 1),
            date(2024, 1, 2),
            context,
            sleep=lambda _: None,
        )

    assert context.page_keys == [None]


def test_permanent_error_with_timeout_text_is_not_retried() -> None:
    context = Context(
        [
            (1, "permission denied: timeout policy is disabled", None),
            (0, page("2024-01-02"), None),
        ]
    )

    with pytest.raises(FutuDownloadError, match="permission denied"):
        download_futu_daily(
            "US.SPY",
            date(2024, 1, 1),
            date(2024, 1, 2),
            context,
            sleep=lambda _: None,
        )

    assert context.page_keys == [None]


def test_second_page_timeout_retries_same_key_without_duplicate_rows() -> None:
    page_2 = b"page-2"
    context = Context(
        [
            (0, page("2024-01-02"), page_2),
            (1, "provider timeout", None),
            (0, page("2024-01-03"), None),
        ]
    )

    data = download_futu_daily(
        "US.SPY",
        date(2024, 1, 1),
        date(2024, 1, 3),
        context,
        sleep=lambda _: None,
    )

    assert context.page_keys == [None, page_2, page_2]
    assert data["timestamp_utc"].dt.date.astype(str).tolist() == [
        "2024-01-02",
        "2024-01-03",
    ]
