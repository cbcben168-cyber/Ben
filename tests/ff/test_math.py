from datetime import date
from math import inf, sqrt

import pytest

from tv_quant.ff.math import calculate_ff, normalize_iv, rank_candidates, select_tenors
from tv_quant.ff.models import ScanStatus


def test_select_tenors_uses_nearest_target_then_earlier_tie():
    expiries = [
        (date(2026, 9, 11), 55),
        (date(2026, 9, 21), 65),
        (date(2026, 10, 12), 86),
        (date(2026, 10, 20), 94),
    ]

    pair = select_tenors(expiries)

    assert (pair.dte1, pair.dte2) == (55, 86)


@pytest.mark.parametrize(
    ("raw", "unit", "expected"),
    [(14.794, "percent", 0.14794), (0.14794, "decimal", 0.14794)],
)
def test_normalize_iv_has_explicit_unit(raw, unit, expected):
    assert normalize_iv(raw, unit) == pytest.approx(expected)


def test_normalize_iv_rejects_unsupported_units_and_invalid_values():
    with pytest.raises(ValueError):
        normalize_iv(14.794, "auto")
    with pytest.raises(ValueError):
        normalize_iv(inf, "decimal")


def test_ff_threshold_is_strict_and_invalid_values_fail_closed():
    threshold = calculate_ff(0.30, sqrt(0.07625), 60, 120)

    assert threshold.ff == pytest.approx(0.20, abs=1e-10)
    assert threshold.status == ScanStatus.SCANNED
    assert calculate_ff(0.30, 0.20, 90, 60).status == ScanStatus.HOLD_INVALID_TENOR_ORDER
    assert calculate_ff(inf, 0.20, 60, 90).status == ScanStatus.HOLD_IV_UNIT_OR_RANGE_ERROR


def test_ff_just_above_threshold_is_a_buy_candidate():
    target_ff = 0.2000000000005
    sigma_1 = 0.30
    sigma_forward = sigma_1 / (1 + target_ff)
    sigma_2 = sqrt((sigma_forward**2 + sigma_1**2) / 2)

    result = calculate_ff(sigma_1, sigma_2, 60, 120)

    assert result.ff > 0.20
    assert result.status == ScanStatus.BUY_CANDIDATE


def test_rank_candidates_sorts_by_ff_then_spread_then_ticker():
    rows = [
        {"ticker": "SPY", "ff": 0.3, "relative_spread": 0.1},
        {"ticker": "QQQ", "ff": 0.3, "relative_spread": 0.1},
        {"ticker": "IWM", "ff": 0.4, "relative_spread": 0.2},
    ]

    assert [row["ticker"] for row in rank_candidates(rows)] == ["IWM", "QQQ", "SPY"]
