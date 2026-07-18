"""Pure forward-factor selection, normalization, and calculation functions."""

from __future__ import annotations

import math
from datetime import date
from typing import Iterable, Mapping

from .models import FFResult, ScanStatus, TenorPair


def normalize_iv(raw: float, unit: str) -> float:
    """Normalize a finite positive IV with an explicitly declared source unit."""
    if unit == "percent":
        value = raw / 100.0
    elif unit == "decimal":
        value = raw
    else:
        raise ValueError("IV unit must be 'percent' or 'decimal'")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("IV must be finite and positive")
    return value


def select_tenors(expiries: Iterable[tuple[date, int]]) -> TenorPair | None:
    """Select 60- and 90-DTE expiries by distance, then earlier expiry."""
    values = tuple(expiries)
    near = _select_tenor(values, target=60, minimum=55, maximum=65)
    far = _select_tenor(values, target=90, minimum=85, maximum=95)
    if near is None or far is None or far[1] <= near[1]:
        return None
    return TenorPair(near[0], near[1], far[0], far[1])


def calculate_ff(sigma_1: float, sigma_2: float, dte1: int, dte2: int) -> FFResult:
    """Calculate forward factor using the specified fail-closed branch order."""
    if not all(math.isfinite(v) and v > 0 for v in (sigma_1, sigma_2)):
        return FFResult(None, None, None, ScanStatus.HOLD_IV_UNIT_OR_RANGE_ERROR)
    t1, t2 = dte1 / 365.0, dte2 / 365.0
    if t2 <= t1:
        return FFResult(None, None, None, ScanStatus.HOLD_INVALID_TENOR_ORDER)
    variance = ((sigma_2**2 * t2) - (sigma_1**2 * t1)) / (t2 - t1)
    if not math.isfinite(variance) or variance <= 0:
        return FFResult(variance, None, None, ScanStatus.HOLD_INVALID_FORWARD_VARIANCE)
    sigma_forward = math.sqrt(variance)
    if not math.isfinite(sigma_forward) or sigma_forward <= 0:
        return FFResult(variance, sigma_forward, None, ScanStatus.HOLD_INVALID_FORWARD_VOLATILITY)
    ff = (sigma_1 - sigma_forward) / sigma_forward
    status = ScanStatus.BUY_CANDIDATE if ff > 0.20 else ScanStatus.SCANNED
    return FFResult(variance, sigma_forward, ff, status)


def rank_candidates(rows: Iterable[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """Return candidates ordered by FF, spread, then ticker without mutating inputs."""
    return sorted(
        rows,
        key=lambda row: (-float(row["ff"]), float(row["relative_spread"]), str(row["ticker"])),
    )


def _select_tenor(
    expiries: Iterable[tuple[date, int]], *, target: int, minimum: int, maximum: int
) -> tuple[date, int] | None:
    eligible = (item for item in expiries if minimum <= item[1] <= maximum)
    return min(eligible, key=lambda item: (abs(item[1] - target), item[0]), default=None)
