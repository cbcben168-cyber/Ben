from dataclasses import replace
from datetime import date, datetime

import pytest

from tv_quant.ff.structures import build_atm_call_calendar, build_double_calendar
from tv_quant.ff.models import OptionLeg


T1 = date(2026, 9, 18)
T2 = date(2026, 10, 16)


def option_leg(
    expiry: date, option_type: str, strike: float, delta: float, **changes: object
) -> OptionLeg:
    values: dict[str, object] = {
        "ticker": "SPY",
        "expiry": expiry,
        "option_type": option_type,
        "strike": strike,
        "bid": 0.93,
        "ask": 1.07,
        "iv": 0.2,
        "delta": delta,
        "open_interest": 500,
        "volume": 50,
    }
    values.update(changes)
    return OptionLeg(**values)  # type: ignore[arg-type]


def fixture_chain(*, missing_t2_put_same_strike: bool = False) -> list[OptionLeg]:
    legs = [
        option_leg(T1, "CALL", 599.0, 0.35),
        option_leg(T1, "PUT", 595.0, -0.35),
        option_leg(T1, "CALL", 600.0, 0.50),
        option_leg(T2, "CALL", 599.0, 0.35),
        option_leg(T2, "PUT", 595.0, -0.35),
        option_leg(T2, "PUT", 600.0, -0.50),
        option_leg(T2, "CALL", 600.0, 0.50),
    ]
    if missing_t2_put_same_strike:
        return [leg for leg in legs if not (leg.expiry == T2 and leg.option_type == "PUT" and leg.strike == 595.0)]
    return legs


def test_atm_call_calendar_selects_nearest_spot_then_lower_strike_and_exact_far_leg():
    result = build_atm_call_calendar(fixture_chain(), spot=599.5, t1_expiry=T1, t2_expiry=T2)

    assert result.failed_fields == ()
    assert result.structure is not None
    assert [leg.strike for leg in result.structure] == [599.0, 599.0]
    assert [leg.expiry for leg in result.structure] == [T1, T2]


def test_atm_call_calendar_fails_when_exact_far_strike_is_absent():
    chain = [leg for leg in fixture_chain() if not (leg.expiry == T2 and leg.option_type == "CALL" and leg.strike == 599.0)]

    result = build_atm_call_calendar(chain, spot=599.0, t1_expiry=T1, t2_expiry=T2)

    assert result.structure is None
    assert result.failed_fields == ("t2_call_same_strike",)


def test_double_calendar_uses_nearest_delta_then_lower_strike_and_exact_far_legs():
    result = build_double_calendar(fixture_chain(), t1_expiry=T1, t2_expiry=T2)

    assert result.failed_fields == ()
    assert result.structure is not None
    assert [(leg.expiry, leg.option_type, leg.strike) for leg in result.structure] == [
        (T1, "CALL", 599.0),
        (T2, "CALL", 599.0),
        (T1, "PUT", 595.0),
        (T2, "PUT", 595.0),
    ]


def test_double_calendar_never_substitutes_neighbor_delta():
    result = build_double_calendar(fixture_chain(missing_t2_put_same_strike=True), t1_expiry=T1, t2_expiry=T2)

    assert result.structure is None
    assert result.failed_fields == ("t2_put_same_strike",)


def test_structure_rejects_a_selected_leg_with_nan_quote_data():
    chain = fixture_chain()
    chain[0] = replace(chain[0], bid=float("nan"))

    result = build_double_calendar(chain, t1_expiry=T1, t2_expiry=T2)

    assert result.structure is None
    assert "t1_call_relative_spread" in result.failed_fields


def test_structure_rejects_a_selected_leg_with_nan_execution_activity():
    chain = fixture_chain()
    chain[1] = replace(chain[1], volume=float("nan"))

    result = build_double_calendar(chain, t1_expiry=T1, t2_expiry=T2)

    assert result.structure is None
    assert result.failed_fields == ("t1_put_volume",)


@pytest.mark.parametrize(
    ("field", "invalid_value", "expected_field"),
    [
        pytest.param("strike", float("nan"), "chain_strike", id="nan-strike"),
        pytest.param("strike", 0.0, "chain_strike", id="zero-strike"),
        pytest.param("iv", 0.0, "chain_iv", id="zero-iv"),
        pytest.param("delta", float("nan"), "chain_delta", id="nan-delta"),
    ],
)
def test_invalid_contract_fields_fail_closed_before_neighbor_selection(
    field: str, invalid_value: object, expected_field: str
):
    chain = fixture_chain()
    chain[2] = replace(chain[2], **{field: invalid_value})

    result = build_double_calendar(chain, t1_expiry=T1, t2_expiry=T2)

    assert result.structure is None
    assert result.failed_fields == (expected_field,)


@pytest.mark.parametrize(
    ("changes", "expected_field"),
    [
        pytest.param({"ticker": "QQQ"}, "chain_ticker", id="mixed-ticker"),
        pytest.param({"ticker": " "}, "chain_ticker", id="empty-ticker"),
        pytest.param({"option_type": "WARRANT"}, "chain_option_type", id="invalid-type"),
        pytest.param(
            {"expiry": date(2026, 11, 20)},
            "chain_expiry",
            id="unexpected-expiry",
        ),
        pytest.param(
            {"expiry": datetime(2026, 9, 18)},
            "chain_expiry",
            id="datetime-expiry",
        ),
    ],
)
def test_inconsistent_contract_identity_fails_closed(
    changes: dict[str, object], expected_field: str
):
    chain = fixture_chain()
    chain[2] = replace(chain[2], **changes)

    result = build_double_calendar(chain, t1_expiry=T1, t2_expiry=T2)

    assert result.structure is None
    assert result.failed_fields == (expected_field,)


@pytest.mark.parametrize(
    "spot",
    [
        pytest.param(float("nan"), id="nan"),
        pytest.param(float("inf"), id="infinity"),
        pytest.param(0.0, id="zero"),
        pytest.param(-1.0, id="negative"),
        pytest.param(True, id="boolean"),
    ],
)
def test_atm_call_calendar_rejects_invalid_spot(spot: object):
    result = build_atm_call_calendar(
        fixture_chain(),
        spot=spot,  # type: ignore[arg-type]
        t1_expiry=T1,
        t2_expiry=T2,
    )

    assert result.structure is None
    assert result.failed_fields == ("spot",)
