from datetime import date
import pandas as pd
import pytest
from tv_quant.futu_downloader import FutuDownloadError, download_futu_daily, update_futu_csv

class Context:
    def __init__(self, pages): self.pages, self.keys = iter(pages), []
    def request_history_kline(self, **kwargs): self.keys.append(kwargs["page_req_key"]); return next(self.pages)
def page(day): return pd.DataFrame({"code":["US.SPY"],"time_key":[f"{day} 00:00:00"],"open":[100.],"high":[101.],"low":[99.],"close":[100.5],"volume":[1000]})

def test_pagination_and_utc_contract():
    context = Context([(0,page("2024-01-02"),b"next"),(0,page("2024-01-03"),None)])
    data = download_futu_daily("US.SPY",date(2024,1,1),date(2024,1,3),context,sleep=lambda _:None)
    assert context.keys == [None,b"next"] and data["ticker"].tolist() == ["SPY","SPY"]
    assert data["timestamp_utc"].dt.strftime("%Y-%m-%dT%H:%M:%SZ").tolist() == ["2024-01-02T00:00:00Z","2024-01-03T00:00:00Z"]

def test_failure_is_explicit_and_preserves_csv(tmp_path):
    target=tmp_path/"SPY_daily.csv"; page("2024-01-01").assign(ticker="SPY").to_csv(target,index=False)
    with pytest.raises(FutuDownloadError,match="unavailable"):
        update_futu_csv(target,"US.SPY",date(2024,1,1),date(2024,1,2),Context([(1,"unavailable",None)]),sleep=lambda _:None)
    assert pd.read_csv(target)["close"].tolist()==[100.5]
