import pandas as pd
import pytest

from tv_quant.metrics import calculate_metrics
from tv_quant.reporting import write_reports


def test_calculate_metrics_uses_peak_to_trough_max_drawdown():
    equity = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2024-01-01", periods=4, freq="D", tz="UTC"),
            "equity": [100.0, 120.0, 90.0, 110.0],
            "daily_return": [0.0, 0.2, -0.25, 110.0 / 90.0 - 1],
        }
    )

    metrics = calculate_metrics(equity, trades=pd.DataFrame(), initial_cash=100.0)

    assert metrics["total_return"] == pytest.approx(0.10)
    assert metrics["max_drawdown"] == pytest.approx(-0.25)
    assert metrics["trade_count"] == 0
    assert metrics["win_rate"] is None


def test_trade_count_includes_an_open_position_fill():
    equity = pd.DataFrame(
        {
            "timestamp_utc": pd.date_range("2024-01-01", periods=2, freq="D", tz="UTC"),
            "equity": [100.0, 101.0],
            "daily_return": [0.0, 0.01],
        }
    )
    trades = pd.DataFrame([{"side": "BUY", "net_cash_flow": -100.0}])

    metrics = calculate_metrics(equity, trades=trades, initial_cash=100.0)

    assert metrics["trade_count"] == 1
    assert metrics["win_rate"] is None


def test_write_reports_emits_required_json_and_csv_fields(tmp_path):
    equity = pd.DataFrame(
        {
            "timestamp_utc": [pd.Timestamp("2024-01-01", tz="UTC")],
            "cash": [100.0],
            "shares": [0],
            "close": [100.0],
            "position_value": [0.0],
            "equity": [100.0],
            "daily_return": [0.0],
            "drawdown": [0.0],
        }
    )
    trades = pd.DataFrame(
        columns=[
            "timestamp_utc", "side", "shares", "signal_timestamp_utc", "market_open",
            "execution_price", "slippage_bps", "gross_notional", "commission", "net_cash_flow",
        ]
    )

    paths = write_reports(tmp_path, {"ticker": "SPY", "total_return": 0.0}, equity, trades)

    assert set(paths) == {"summary", "equity", "trades"}
    assert paths["summary"].is_file()
    assert list(pd.read_csv(paths["equity"]).columns) == list(equity.columns)
    assert list(pd.read_csv(paths["trades"]).columns) == list(trades.columns)
