from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from tv_quant.ff.models import FFResult, OptionLeg, ScanStatus, TenorPair, make_signal_id


def test_signal_id_is_deterministic_sha256_for_canonical_values():
    value = make_signal_id(
        "ff-v1", date(2026, 7, 17), "SPY", date(2026, 9, 18), date(2026, 10, 16)
    )

    assert value == make_signal_id(
        "ff-v1", date(2026, 7, 17), "SPY", date(2026, 9, 18), date(2026, 10, 16)
    )
    assert len(value) == 64
    assert value != make_signal_id(
        "ff-v1", date(2026, 7, 17), "QQQ", date(2026, 9, 18), date(2026, 10, 16)
    )


def test_domain_contracts_are_immutable():
    pair = TenorPair(date(2026, 9, 18), 60, date(2026, 10, 16), 88)
    result = FFResult(0.04, 0.20, 0.25, ScanStatus.BUY_CANDIDATE)
    leg = OptionLeg(
        ticker="SPY",
        expiry=date(2026, 9, 18),
        option_type="call",
        strike=650.0,
        bid=1.0,
        ask=1.1,
        iv=0.2,
        delta=0.5,
        open_interest=500,
        volume=50,
    )

    with pytest.raises(FrozenInstanceError):
        pair.dte1 = 61
    with pytest.raises(FrozenInstanceError):
        result.ff = 0.3
    with pytest.raises(FrozenInstanceError):
        leg.bid = 0.9
