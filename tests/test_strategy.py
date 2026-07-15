import math

import pandas as pd

from tv_quant.strategy import run_backtest


def crossover_data() -> pd.DataFrame:
    dates = pd.date_range("2020-01-01", periods=203, freq="B", tz="UTC")
    close = [100.0] * 200 + [200.0, 200.0, 200.0]
    open_prices = [100.0] * 200 + [100.0, 150.0, 200.0]
    return pd.DataFrame(
        {
            "timestamp_utc": dates,
            "ticker": ["SPY"] * len(dates),
            "open": open_prices,
            "high": [max(open_price, close_price) + 1 for open_price, close_price in zip(open_prices, close)],
            "low": [min(open_price, close_price) - 1 for open_price, close_price in zip(open_prices, close)],
            "close": close,
            "volume": [1_000_000] * len(dates),
        }
    )


def test_golden_cross_fills_at_the_next_bar_open_not_signal_close():
    data = crossover_data()

    result = run_backtest(data, initial_cash=100_000, commission_bps=5, slippage_bps=5)

    trade = result.trades.iloc[0]
    assert trade["side"] == "BUY"
    assert trade["signal_timestamp_utc"] == data.loc[200, "timestamp_utc"]
    assert trade["timestamp_utc"] == data.loc[201, "timestamp_utc"]
    assert trade["market_open"] == 150.0
    assert trade["execution_price"] == 150.0 * 1.0005


def test_buy_uses_integer_shares_and_debits_slippage_and_commission():
    result = run_backtest(crossover_data(), initial_cash=100_000, commission_bps=5, slippage_bps=5)

    trade = result.trades.iloc[0]
    expected_price = 150.0 * 1.0005
    expected_shares = math.floor(100_000 / (expected_price * 1.0005))
    expected_notional = expected_shares * expected_price

    assert trade["shares"] == expected_shares
    assert trade["gross_notional"] == expected_notional
    assert trade["commission"] == expected_notional * 0.0005
    assert trade["net_cash_flow"] == -(expected_notional + trade["commission"])


def test_death_cross_sells_at_the_next_bar_open_with_unfavorable_costs():
    data = crossover_data()
    tail_dates = pd.date_range(data["timestamp_utc"].iloc[-1] + pd.offsets.BDay(), periods=100, freq="B", tz="UTC")
    tail = pd.DataFrame(
        {
            "timestamp_utc": tail_dates,
            "ticker": ["SPY"] * len(tail_dates),
            "open": [50.0] * len(tail_dates),
            "high": [51.0] * len(tail_dates),
            "low": [0.5] * len(tail_dates),
            "close": [1.0] * len(tail_dates),
            "volume": [1_000_000] * len(tail_dates),
        }
    )

    result = run_backtest(pd.concat([data, tail], ignore_index=True), commission_bps=5, slippage_bps=5)

    sell = result.trades[result.trades["side"] == "SELL"].iloc[0]
    assert sell["timestamp_utc"] == sell["signal_timestamp_utc"] + pd.offsets.BDay()
    assert sell["execution_price"] == 50.0 * 0.9995
    assert sell["commission"] == sell["gross_notional"] * 0.0005
