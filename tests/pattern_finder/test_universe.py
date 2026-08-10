import pytest

from tv_quant.pattern_finder.universe import (
    M3B_SYMBOLS,
    M3B_UNIVERSE,
    PILOT_SYMBOLS,
    futu_code,
)


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
    assert futu_code(" cat ") == "US.CAT"

    with pytest.raises(ValueError, match="M3B universe"):
        futu_code("SPY")


def test_m3b_universe_has_100_unique_diversified_common_stocks() -> None:
    assert len(M3B_UNIVERSE) == 100
    assert len(M3B_SYMBOLS) == 100
    assert len(set(M3B_SYMBOLS)) == 100
    assert set(PILOT_SYMBOLS) <= set(M3B_SYMBOLS)
    assert {member.sector for member in M3B_UNIVERSE} >= {
        "Technology",
        "Semiconductor",
        "Financial",
        "Energy",
        "Health Care",
        "Consumer",
        "Industrial",
    }
    assert {member.volatility_bucket for member in M3B_UNIVERSE} == {
        "低",
        "中",
        "高",
    }
