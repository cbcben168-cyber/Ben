import pytest

from tv_quant.pattern_finder.universe import PILOT_SYMBOLS, futu_code


def test_pilot_universe_contains_only_approved_common_stocks() -> None:
    assert PILOT_SYMBOLS == (
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "META",
        "GOOGL",
        "JPM",
        "XOM",
    )


def test_futu_code_normalizes_approved_symbol_and_rejects_outside_universe() -> None:
    assert futu_code(" aapl ") == "US.AAPL"

    with pytest.raises(ValueError, match="pilot universe"):
        futu_code("SPY")
