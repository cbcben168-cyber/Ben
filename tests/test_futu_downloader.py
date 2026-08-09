from datetime import date
import pandas as pd
import pytest
from tv_quant.futu_downloader import FutuDownloadError, download_futu_daily, futu_to_standardized, update_futu_csv

class Context:
    def __init__(self, pages): self.pages, self.keys = iter(pages), []
    def request_history_kline(self, **kwargs): self.keys.append(kwargs["page_req_key"]); return next(self.pages)
def page(day): return pd.DataFrame({"code":["US.SPY"],"time_key":[f"{day} 00:00:00"],"open":[100.],"high":[101.],"low":[99.],"close":[100.5],"volume":[1000]})

def test_pagination_and_utc_contract():
    context = Context([(0,page("2024-01-02"),b"next"),(0,page("2024-01-03"),None)])
    data = download_futu_daily("US.SPY",date(2024,1,1),date(2024,1,3),context,sleep=lambda _:None)
    assert context.keys == [None,b"next"] and data["ticker"].tolist() == ["SPY","SPY"]
    assert data["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist() == ["2024-01-02T00:00:00Z","2024-01-03T00:00:00Z"]


def test_conversion_rejects_unsupported_or_mismatched_ticker():
    bad = page("2024-01-02").assign(code="US.XYZ")
    with pytest.raises(FutuDownloadError, match="supported ticker"):
        download_futu_daily("US.SPY", date(2024, 1, 1), date(2024, 1, 2), Context([(0, bad, None)]), sleep=lambda _: None)


def test_pattern_finder_may_explicitly_allow_aapl_without_weakening_default_allowlist():
    aapl = page("2024-01-02").assign(code="US.AAPL")

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
    wrong = page("2024-01-02").assign(code="US.MSFT")

    with pytest.raises(FutuDownloadError, match="requested US.AAPL"):
        download_futu_daily(
            "US.AAPL",
            date(2024, 1, 1),
            date(2024, 1, 2),
            Context([(0, wrong, None)]),
            allowed_tickers={"AAPL", "MSFT"},
            sleep=lambda _: None,
        )

def test_failure_is_explicit_and_preserves_csv(tmp_path):
    target=tmp_path/"SPY_daily.csv"; page("2024-01-01").assign(ticker="SPY").to_csv(target,index=False)
    with pytest.raises(FutuDownloadError,match="unavailable"):
        update_futu_csv(target,"US.SPY",date(2024,1,1),date(2024,1,2),Context([(1,"unavailable",None)]),sleep=lambda _:None)
    assert pd.read_csv(target)["close"].tolist()==[100.5]


def test_post_download_check_failure_preserves_existing_csv(tmp_path):
    target = tmp_path / "SPY_daily.csv"
    futu_to_standardized(page("2024-01-01")).to_csv(target, index=False)
    with pytest.raises(RuntimeError, match="quota post-check failed"):
        update_futu_csv(
            target, "US.SPY", date(2024, 1, 1), date(2024, 1, 2),
            Context([(0, page("2024-01-02"), None)]), sleep=lambda _: None,
            before_replace=lambda _: (_ for _ in ()).throw(RuntimeError("quota post-check failed")),
        )
    assert pd.read_csv(target)["close"].tolist() == [100.5]


def test_incremental_update_reports_new_updated_and_total_rows(tmp_path):
    target = tmp_path / "SPY_daily.csv"
    futu_to_standardized(page("2024-01-01")).to_csv(target, index=False)
    incoming = pd.concat([page("2024-01-01").assign(close=101.5, high=102.0), page("2024-01-02")], ignore_index=True)
    result = update_futu_csv(target, "US.SPY", date(2024, 1, 1), date(2024, 1, 2), Context([(0, incoming, None)]), sleep=lambda _: None)
    assert (result.new_rows, result.updated_rows, result.total_rows) == (1, 1, 2)
    assert pd.read_csv(target)["close"].tolist() == [101.5, 100.5]
