import pytest
from tv_quant.futu_quota import QuotaPolicyError, QuotaSnapshot, check_quota

def quota(remain, codes=(), used=1):
    return QuotaSnapshot(used, remain, [{"code": code} for code in codes])


def test_known_code_is_allowed_when_provider_has_no_new_slots():
    decision = check_quota(quota(0, ("US.SPY",), used=300), " us.spy ")

    assert decision.is_new_code is False
    assert decision.known_code_count == 1
    assert decision.server_used_quota == 300
    assert decision.server_remain_quota == 0


def test_new_code_is_allowed_with_one_provider_slot():
    decision = check_quota(quota(1, ("US.AAPL",)), "US.SPY")

    assert decision.is_new_code is True
    assert decision.known_code_count == 1
    assert decision.server_used_quota == 1
    assert decision.server_remain_quota == 1


def test_new_code_is_blocked_only_when_provider_has_no_slots():
    with pytest.raises(
        QuotaPolicyError,
        match="no remaining historical-K-line quota",
    ):
        check_quota(quota(0), "US.SPY")
