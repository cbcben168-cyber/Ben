"""Pure, fail-closed liquidity gates for forward-factor option structures."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import math
from numbers import Number
from typing import Iterable

from .models import OptionLeg, ScanStatus


@dataclass(frozen=True, slots=True)
class UnderlyingLiquidityResult:
    passed: bool
    status: ScanStatus
    failed_fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LegLiquidityResult:
    passed: bool
    failed_fields: tuple[str, ...] = ()


def check_underlying_liquidity(observations: Iterable[int | float | None]) -> UnderlyingLiquidityResult:
    """Require exactly 20 complete recent sessions with mean volume strictly above 10,000."""
    sessions = tuple(observations)
    if len(sessions) < 20:
        return UnderlyingLiquidityResult(False, ScanStatus.HOLD_LIQUIDITY_WARMUP)
    if len(sessions) > 20 or any(not _is_finite_nonnegative(value) for value in sessions):
        return UnderlyingLiquidityResult(
            False,
            ScanStatus.HOLD_LIQUIDITY_HISTORY_GAP,
            ("observations",),
        )
    passed = sum(float(value) for value in sessions) / 20 > 10_000
    return UnderlyingLiquidityResult(passed, ScanStatus.SCANNED, () if passed else ("mean_volume",))


def check_leg_liquidity(leg: OptionLeg) -> LegLiquidityResult:
    """Validate the execution liquidity requirements for one option contract."""
    mid = (leg.bid + leg.ask) / 2
    failed_fields: list[str] = []
    bid_is_valid = math.isfinite(leg.bid) and leg.bid > 0
    ask_is_valid = math.isfinite(leg.ask)
    mid_is_valid = math.isfinite(mid) and mid > 0
    if not bid_is_valid:
        failed_fields.append("bid")
    if not (ask_is_valid and leg.ask > leg.bid):
        failed_fields.append("ask_greater_than_bid")
    if not mid_is_valid:
        failed_fields.append("mid")
    if not (ask_is_valid and bid_is_valid and mid_is_valid):
        failed_fields.append("relative_spread")
    else:
        decimal_mid = (Decimal(str(leg.bid)) + Decimal(str(leg.ask))) / 2
        relative_spread = (Decimal(str(leg.ask)) - Decimal(str(leg.bid))) / decimal_mid
        if relative_spread > Decimal("0.15"):
            failed_fields.append("relative_spread")
    if not _is_finite_at_least(leg.open_interest, 500):
        failed_fields.append("open_interest")
    if not _is_finite_at_least(leg.volume, 50):
        failed_fields.append("volume")
    fields = tuple(sorted(failed_fields))
    return LegLiquidityResult(not fields, fields)


def _is_finite_at_least(value: object, threshold: int) -> bool:
    """Return whether a runtime numeric value is finite and meets a minimum."""
    if isinstance(value, bool) or not isinstance(value, (Number, Decimal)):
        return False
    try:
        numeric_value = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(numeric_value) and numeric_value >= threshold


def _is_finite_nonnegative(value: object) -> bool:
    """Return whether a runtime observation is numeric, finite, and nonnegative."""
    return _is_finite_at_least(value, 0)
