from datetime import date

import pandas as pd
import pytest

from tv_quant.futu_downloader import FutuDownloadError, download_futu_daily


class Context:
    def __init__(self, pages):
        self.pages = iter(pages)

    def request_history_kline(self, **kwargs):
        return next(self.pages)


def _page(day: str, symbol: str) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "code": [f"US.{symbol}"],
            "time_key": [f"{day} 00:00:00"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1_000],
        }
    )


def test_pattern_finder_may_explicitly_allow_aapl_without_weakening_default_allowlist():
    aapl = _page("2024-01-02", "AAPL")

    data = download_futu_daily(
        "US.AAPL",
        date(2024, 1, 1),
        date(2024, 1, 2),
        Context([(0, aapl, None)]),
        allowed_tickers={"AAPL"},
        sleep=lambda _: None,
    )

    assert data["ticker"].tolist() == ["AAPL"]
    with pytest.raises(FutuDownloadError, match="supported ticker"):
        download_futu_daily(
            "US.AAPL",
            date(2024, 1, 1),
            date(2024, 1, 2),
            Context([(0, aapl, None)]),
            sleep=lambda _: None,
        )


def test_explicit_allowlist_still_rejects_response_for_another_symbol():
    wrong = _page("2024-01-02", "MSFT")

    with pytest.raises(FutuDownloadError, match="requested US.AAPL"):
        download_futu_daily(
            "US.AAPL",
            date(2024, 1, 1),
            date(2024, 1, 2),
            Context([(0, wrong, None)]),
            allowed_tickers={"AAPL", "MSFT"},
            sleep=lambda _: None,
        )
