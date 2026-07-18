"""Immutable, provider-independent forward-factor domain contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from hashlib import sha256


class ScanStatus(str, Enum):
    """Stable scan outcomes and signal lifecycle states."""

    SCANNED = "SCANNED"
    BUY_CANDIDATE = "BUY_CANDIDATE"
    NOTIFIED = "NOTIFIED"
    EXPIRED = "EXPIRED"
    HOLD_DTE_UNAVAILABLE = "HOLD_DTE_UNAVAILABLE"
    HOLD_ATM_IV_INCOMPLETE = "HOLD_ATM_IV_INCOMPLETE"
    HOLD_INVALID_TENOR_ORDER = "HOLD_INVALID_TENOR_ORDER"
    HOLD_INVALID_FORWARD_VARIANCE = "HOLD_INVALID_FORWARD_VARIANCE"
    HOLD_INVALID_FORWARD_VOLATILITY = "HOLD_INVALID_FORWARD_VOLATILITY"
    HOLD_IV_UNIT_OR_RANGE_ERROR = "HOLD_IV_UNIT_OR_RANGE_ERROR"
    HOLD_LIQUIDITY_WARMUP = "HOLD_LIQUIDITY_WARMUP"
    HOLD_LIQUIDITY_HISTORY_GAP = "HOLD_LIQUIDITY_HISTORY_GAP"
    HOLD_EARNINGS_UNKNOWN = "HOLD_EARNINGS_UNKNOWN"
    HOLD_EARNINGS_BEFORE_T2 = "HOLD_EARNINGS_BEFORE_T2"
    HOLD_MARKET_DATA_TIMEOUT = "HOLD_MARKET_DATA_TIMEOUT"
    HOLD_OPTION_CHAIN_INCOMPLETE = "HOLD_OPTION_CHAIN_INCOMPLETE"
    EARNINGS_NOT_APPLICABLE = "EARNINGS_NOT_APPLICABLE"
    SKIPPED_NON_TRADING_DAY = "SKIPPED_NON_TRADING_DAY"
    FAILED_UNCLASSIFIED = "FAILED_UNCLASSIFIED"


@dataclass(frozen=True, slots=True)
class OptionLeg:
    """A normalized option-chain row used by the pure selection rules."""

    ticker: str
    expiry: date
    option_type: str
    strike: float
    bid: float
    ask: float
    iv: float
    delta: float
    open_interest: int
    volume: int
    contract_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class TenorPair:
    """Selected near and far expiries with their calendar DTE values."""

    expiry1: date
    dte1: int
    expiry2: date
    dte2: int


@dataclass(frozen=True, slots=True)
class FFResult:
    """Forward-variance and forward-factor calculation result."""

    forward_variance: float | None
    sigma_forward: float | None
    ff: float | None
    status: ScanStatus


def make_signal_id(
    strategy_version: str,
    scan_date: date,
    ticker: str,
    expiry1: date,
    expiry2: date,
) -> str:
    """Return the SHA-256 ID for canonical signal identity fields."""
    canonical = "|".join(
        (strategy_version, scan_date.isoformat(), ticker, expiry1.isoformat(), expiry2.isoformat())
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
