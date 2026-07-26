"""Canonical scalar numeric values for immutable V2 contract payloads."""

from decimal import Decimal, InvalidOperation
import re


_DECIMAL_TEXT = re.compile(r"[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")


def _decimal(value: object, path: str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{path}: binary float values are not permitted")
    if isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, Decimal):
        result = value
    elif isinstance(value, str) and _DECIMAL_TEXT.fullmatch(value):
        try:
            result = Decimal(value)
        except InvalidOperation as error:  # pragma: no cover - regex guards this
            raise ValueError(f"{path}: invalid decimal value") from error
    else:
        raise ValueError(f"{path}: invalid decimal value")
    if not result.is_finite():
        raise ValueError(f"{path}: non-finite decimal value")
    return result


def canonical_decimal(value: object, path: str) -> str:
    """Return a finite decimal as its unique non-exponent canonical string."""
    result = _decimal(value, path)
    if result.is_zero():
        return "0"
    normalized = format(result.normalize(), "f")
    return normalized.rstrip("0").rstrip(".") if "." in normalized else normalized


def canonical_integer(value: object, path: str) -> int:
    """Return an exact finite integer, rejecting fractional and float inputs."""
    result = _decimal(value, path)
    if result != result.to_integral_value():
        raise ValueError(f"{path}: integer value required")
    return int(result)
