from dataclasses import replace
from datetime import date

import pytest

from tv_quant.ff.liquidity import check_leg_liquidity, check_underlying_liquidity
from tv_quant.ff.models import OptionLeg, ScanStatus


def option_leg(**changes: object) -> OptionLeg:
    values: dict[str, object] = {
        "ticker": "SPY",
        "expiry": date(2026, 9, 18),
        "option_type": "CALL",
        "strike": 600.0,
        "bid": 0.93,
        "ask": 1.07,
        "iv": 0.2,
        "delta": 0.35,
        "open_interest": 500,
        "volume": 50,
    }
    values.update(changes)
    return OptionLeg(**values)  # type: ignore[arg-type]


def test_underlying_gate_requires_20_complete_sessions_and_strict_mean():
    assert check_underlying_liquidity([10_001] * 19).status == ScanStatus.HOLD_LIQUIDITY_WARMUP
    assert check_underlying_liquidity([10_000] * 20).passed is False
    assert check_underlying_liquidity([10_001] * 20).passed is True
    assert (
        check_underlying_liquidity([10_001] * 10 + [None] + [10_001] * 9).status
        == ScanStatus.HOLD_LIQUIDITY_HISTORY_GAP
    )
    assert check_underlying_liquidity([10_001] * 21).status == ScanStatus.HOLD_LIQUIDITY_HISTORY_GAP


@pytest.mark.parametrize(
    "invalid_value",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinity"),
        pytest.param(-1, id="negative"),
        pytest.param(True, id="boolean"),
        pytest.param("10001", id="string"),
    ],
)
def test_underlying_gate_rejects_invalid_observations_with_stable_failed_fields(
    invalid_value: object,
):
    observations: list[object] = [10_001] * 20
    observations[7] = invalid_value

    result = check_underlying_liquidity(observations)  # type: ignore[arg-type]

    assert result.passed is False
    assert result.status == ScanStatus.HOLD_LIQUIDITY_HISTORY_GAP
    assert result.failed_fields == ("observations",)


@pytest.mark.parametrize(
    ("changes", "expected_failed_fields"),
    [
        ({"bid": 0.0}, ("bid", "relative_spread")),
        ({"ask": 0.93}, ("ask_greater_than_bid",)),
        ({"ask": 1.09}, ("relative_spread",)),
        ({"open_interest": 499}, ("open_interest",)),
        ({"volume": 49}, ("volume",)),
        ({"bid": -1.0, "ask": -0.5}, ("bid", "mid", "relative_spread")),
    ],
)
def test_leg_gate_reports_each_failed_threshold_in_lexical_order(
    changes: dict[str, object], expected_failed_fields: tuple[str, ...]
):
    result = check_leg_liquidity(replace(option_leg(), **changes))

    assert result.passed is False
    assert result.failed_fields == expected_failed_fields


def test_leg_gate_checks_every_exact_threshold():
    leg = option_leg()

    assert check_leg_liquidity(leg).passed is True
    assert check_leg_liquidity(replace(leg, ask=1.09)).failed_fields == ("relative_spread",)


def test_leg_gate_accepts_an_exact_15_percent_relative_spread():
    result = check_leg_liquidity(option_leg(bid=0.925, ask=1.075))

    assert result.passed is True


@pytest.mark.parametrize("field", ("bid", "ask"))
def test_leg_gate_rejects_nan_prices(field: str):
    result = check_leg_liquidity(replace(option_leg(), **{field: float("nan")}))

    assert result.passed is False
    assert result.failed_fields == tuple(sorted(result.failed_fields))
    assert "relative_spread" in result.failed_fields


@pytest.mark.parametrize(
    ("field", "expected_field"),
    (("open_interest", "open_interest"), ("volume", "volume")),
)
def test_leg_gate_rejects_nan_execution_activity(field: str, expected_field: str):
    result = check_leg_liquidity(replace(option_leg(), **{field: float("nan")}))

    assert result.passed is False
    assert result.failed_fields == (expected_field,)
