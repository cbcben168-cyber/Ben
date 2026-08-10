from __future__ import annotations

from dataclasses import dataclass


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

M3B_SECTOR_SYMBOLS = {
    "Technology": (
        "AAPL", "MSFT", "ORCL", "CRM", "ADBE", "NOW", "IBM", "INTU", "PANW", "CSCO",
    ),
    "Semiconductor": (
        "NVDA", "AMD", "AVGO", "QCOM", "TXN", "MU", "AMAT", "LRCX", "KLAC", "INTC",
    ),
    "Financial": (
        "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK", "SCHW", "AXP", "COF", "USB", "PNC",
    ),
    "Energy": (
        "XOM", "CVX", "COP", "SLB", "EOG", "OXY", "MPC", "PSX", "VLO", "HAL",
    ),
    "Health Care": (
        "JNJ", "UNH", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "AMGN", "GILD", "CVS", "BMY",
    ),
    "Consumer": (
        "AMZN", "WMT", "COST", "HD", "LOW", "TGT", "MCD", "SBUX", "NKE", "DIS", "PG", "KO", "PEP", "PM", "MO", "TSLA",
    ),
    "Industrial": (
        "CAT", "DE", "HON", "GE", "RTX", "BA", "UPS", "FDX", "LMT", "NOC", "MMM", "ETN", "EMR", "CSX", "UNP",
    ),
    "Communication": (
        "GOOGL", "META", "NFLX", "TMUS", "VZ", "T", "CMCSA",
    ),
    "Utilities": ("NEE", "DUK", "SO", "AEP", "EXC"),
    "Real Estate": ("PLD", "AMT", "SPG"),
}

HIGH_VOLATILITY_SYMBOLS = frozenset(
    {
        "NVDA", "AMD", "MU", "INTC", "TSLA", "META", "NFLX", "BA", "OXY", "COF",
        "PANW", "CRM", "ADBE", "AMZN", "NKE", "TGT", "HAL", "SLB", "LRCX", "AMAT",
    }
)
LOW_VOLATILITY_SYMBOLS = frozenset(
    {
        "JNJ", "PG", "KO", "PEP", "WMT", "COST", "VZ", "T", "IBM", "MRK",
        "PFE", "ABBV", "MCD", "MO", "PM", "NEE", "DUK", "SO", "AEP", "EXC",
    }
)


@dataclass(frozen=True, slots=True)
class UniverseMember:
    symbol: str
    sector: str
    volatility_bucket: str

    def __post_init__(self) -> None:
        if not self.symbol or not self.sector:
            raise ValueError("universe symbol and sector are required")
        if self.volatility_bucket not in {"低", "中", "高"}:
            raise ValueError("volatility_bucket must be 低, 中, or 高")


def _volatility_bucket(symbol: str) -> str:
    if symbol in HIGH_VOLATILITY_SYMBOLS:
        return "高"
    if symbol in LOW_VOLATILITY_SYMBOLS:
        return "低"
    return "中"


M3B_UNIVERSE = tuple(
    UniverseMember(symbol, sector, _volatility_bucket(symbol))
    for sector, symbols in M3B_SECTOR_SYMBOLS.items()
    for symbol in symbols
)
M3B_SYMBOLS = tuple(member.symbol for member in M3B_UNIVERSE)


def futu_code(symbol: str) -> str:
    normalized = symbol.strip().upper()
    if normalized not in M3B_SYMBOLS:
        raise ValueError(f"symbol is outside the M3B universe: {symbol!r}")
    return f"US.{normalized}"
