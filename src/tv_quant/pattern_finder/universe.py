from __future__ import annotations


PILOT_SYMBOLS = (
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "META",
    "GOOGL",
    "JPM",
    "XOM",
)


def futu_code(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized not in PILOT_SYMBOLS:
        raise ValueError(f"symbol is outside the pilot universe: {symbol!r}")
    return f"US.{normalized}"
