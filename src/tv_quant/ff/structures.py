"""Deterministic calendar-structure selection without contract substitution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import math
from numbers import Number
from typing import Iterable

from .liquidity import check_leg_liquidity
from .models import OptionLeg


@dataclass(frozen=True, slots=True)
class StructureResult:
    structure: tuple[OptionLeg, ...] | None
    failed_fields: tuple[str, ...] = ()


def build_atm_call_calendar(
    chain: Iterable[OptionLeg],
    spot: float,
    t1_expiry: date | None = None,
    t2_expiry: date | None = None,
) -> StructureResult:
    """Build an ATM-call calendar, requiring an exact T2 strike match."""
    if not _is_finite_number(spot, positive=True):
        return StructureResult(None, ("spot",))
    legs = tuple(chain)
    invalid_fields = _validate_selector_inputs(legs, t1_expiry, t2_expiry)
    if invalid_fields:
        return StructureResult(None, invalid_fields)
    legs, expiry1, expiry2 = _prepare_chain(legs, t1_expiry, t2_expiry)
    if expiry1 is None or expiry2 is None:
        return StructureResult(None, ("expiries",))
    near_calls = _matching(legs, expiry1, "CALL")
    near_call = min(near_calls, key=lambda leg: (abs(leg.strike - spot), leg.strike), default=None)
    if near_call is None:
        return StructureResult(None, ("t1_atm_call",))
    far_call = _exact_match(legs, expiry2, "CALL", near_call.strike)
    if far_call is None:
        return StructureResult(None, ("t2_call_same_strike",))
    return _liquid_structure((("t1_call", near_call), ("t2_call", far_call)))


def build_double_calendar(
    chain: Iterable[OptionLeg], t1_expiry: date | None = None, t2_expiry: date | None = None
) -> StructureResult:
    """Build a +/-0.35 double calendar with exact T2 strike reuse for both sides."""
    legs = tuple(chain)
    invalid_fields = _validate_selector_inputs(legs, t1_expiry, t2_expiry)
    if invalid_fields:
        return StructureResult(None, invalid_fields)
    legs, expiry1, expiry2 = _prepare_chain(legs, t1_expiry, t2_expiry)
    if expiry1 is None or expiry2 is None:
        return StructureResult(None, ("expiries",))
    near_call = _nearest_delta(_matching(legs, expiry1, "CALL"), 0.35)
    near_put = _nearest_delta(_matching(legs, expiry1, "PUT"), -0.35)
    missing: list[str] = []
    if near_call is None:
        missing.append("t1_call_delta")
    if near_put is None:
        missing.append("t1_put_delta")
    if missing:
        return StructureResult(None, tuple(sorted(missing)))
    far_call = _exact_match(legs, expiry2, "CALL", near_call.strike)
    far_put = _exact_match(legs, expiry2, "PUT", near_put.strike)
    if far_call is None:
        missing.append("t2_call_same_strike")
    if far_put is None:
        missing.append("t2_put_same_strike")
    if missing:
        return StructureResult(None, tuple(sorted(missing)))
    return _liquid_structure(
        (("t1_call", near_call), ("t2_call", far_call), ("t1_put", near_put), ("t2_put", far_put))
    )


def _prepare_chain(
    chain: Iterable[OptionLeg], t1_expiry: date | None, t2_expiry: date | None
) -> tuple[tuple[OptionLeg, ...], date | None, date | None]:
    legs = tuple(chain)
    if t1_expiry is None or t2_expiry is None:
        expiries = sorted({leg.expiry for leg in legs})
        if len(expiries) != 2:
            return legs, None, None
        t1_expiry, t2_expiry = expiries
    if t2_expiry <= t1_expiry:
        return legs, None, None
    return legs, t1_expiry, t2_expiry


def _validate_selector_inputs(
    legs: tuple[OptionLeg, ...],
    t1_expiry: date | None,
    t2_expiry: date | None,
) -> tuple[str, ...]:
    """Validate every field that can influence contract selection before selecting."""
    failed_fields: set[str] = set()
    expected_expiries: set[date] | None = None
    if t1_expiry is not None and t2_expiry is not None:
        if not _is_plain_date(t1_expiry) or not _is_plain_date(t2_expiry):
            failed_fields.add("chain_expiry")
        else:
            expected_expiries = {t1_expiry, t2_expiry}

    canonical_tickers: set[str] = set()
    for leg in legs:
        if not isinstance(leg, OptionLeg):
            failed_fields.add("chain_row")
            continue

        if not isinstance(leg.ticker, str) or not leg.ticker.strip():
            failed_fields.add("chain_ticker")
        else:
            canonical_tickers.add(leg.ticker.strip().upper())

        if not _is_plain_date(leg.expiry) or (
            expected_expiries is not None and leg.expiry not in expected_expiries
        ):
            failed_fields.add("chain_expiry")

        option_type_is_valid = isinstance(leg.option_type, str) and leg.option_type in {
            "CALL",
            "PUT",
        }
        if not option_type_is_valid:
            failed_fields.add("chain_option_type")

        if not _is_finite_number(leg.strike, positive=True):
            failed_fields.add("chain_strike")
        if not _is_finite_number(leg.iv, positive=True):
            failed_fields.add("chain_iv")
        if option_type_is_valid and not _valid_delta(leg.delta, leg.option_type):
            failed_fields.add("chain_delta")

    if len(canonical_tickers) > 1:
        failed_fields.add("chain_ticker")
    return tuple(sorted(failed_fields))


def _is_plain_date(value: object) -> bool:
    return isinstance(value, date) and not isinstance(value, datetime)


def _is_finite_number(value: object, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (Number, Decimal)):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(number) and (number > 0 if positive else True)


def _valid_delta(value: object, option_type: object) -> bool:
    if not _is_finite_number(value):
        return False
    delta = float(value)
    if option_type == "CALL":
        return 0.0 <= delta <= 1.0
    if option_type == "PUT":
        return -1.0 <= delta <= 0.0
    return False


def _matching(legs: Iterable[OptionLeg], expiry: date, option_type: str) -> tuple[OptionLeg, ...]:
    return tuple(leg for leg in legs if leg.expiry == expiry and leg.option_type == option_type)


def _nearest_delta(legs: Iterable[OptionLeg], target: float) -> OptionLeg | None:
    return min(legs, key=lambda leg: (abs(leg.delta - target), leg.strike), default=None)


def _exact_match(
    legs: Iterable[OptionLeg], expiry: date, option_type: str, strike: float
) -> OptionLeg | None:
    return min(
        (leg for leg in legs if leg.expiry == expiry and leg.option_type == option_type and leg.strike == strike),
        key=lambda leg: leg.contract_symbol or "",
        default=None,
    )


def _liquid_structure(named_legs: tuple[tuple[str, OptionLeg], ...]) -> StructureResult:
    failed_fields = tuple(
        sorted(f"{name}_{field}" for name, leg in named_legs for field in check_leg_liquidity(leg).failed_fields)
    )
    if failed_fields:
        return StructureResult(None, failed_fields)
    return StructureResult(tuple(leg for _, leg in named_legs))
