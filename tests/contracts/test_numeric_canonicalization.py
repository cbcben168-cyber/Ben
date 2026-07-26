from decimal import Decimal, localcontext

import pytest

from tv_quant.contracts.numeric import canonical_decimal, canonical_integer


def test_decimal_strings_normalize_1_1_00_to_one_semantic_hash():
    """Equivalent user decimal forms must have one canonical IR representation."""
    assert {
        canonical_decimal(1, "ratio"),
        canonical_decimal(Decimal("1.0"), "ratio"),
        canonical_decimal("1.00", "ratio"),
    } == {"1"}
    assert canonical_decimal("-0.00", "threshold") == "0"


def test_high_precision_decimal_canonicalization_is_context_invariant():
    """Canonical decimals retain every significant digit regardless of context."""
    left = Decimal("123456789012345678901234567890.12345678900100")
    right = Decimal("123456789012345678901234567890.12345678900200")
    expected_left = "123456789012345678901234567890.123456789001"
    expected_right = "123456789012345678901234567890.123456789002"

    with localcontext() as context:
        context.prec = 5
        low_precision = (
            canonical_decimal(left, "ratio"),
            canonical_decimal(right, "ratio"),
        )
    with localcontext() as context:
        context.prec = 80
        high_precision = (
            canonical_decimal(left, "ratio"),
            canonical_decimal(right, "ratio"),
        )

    assert low_precision == (expected_left, expected_right)
    assert high_precision == (expected_left, expected_right)
    assert low_precision[0] != low_precision[1]


def test_initial_capital_and_bps_are_integer_values():
    """USD capital and basis points cannot enter the IR as decimal strings."""
    assert canonical_integer(100000, "initial_capital.amount") == 100000
    assert canonical_integer(Decimal("12.00"), "commission_bps") == 12
    assert canonical_integer("3.0", "slippage_bps") == 3

    with pytest.raises(ValueError, match="commission_bps"):
        canonical_integer("12.5", "commission_bps")


def test_binary_float_and_special_values_do_not_enter_ir():
    """Float input and non-finite Decimal forms are never canonical IR values."""
    for value in (1.0, float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            canonical_decimal(value, "ratio")

    for value in ("NaN", "Infinity", "-Infinity", "1e3", "", "1.2.3"):
        with pytest.raises(ValueError):
            canonical_decimal(value, "threshold")
