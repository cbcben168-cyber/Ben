from datetime import datetime, timedelta, timezone
import pytest
from tv_quant.futu_quota import QuotaPolicyError, QuotaSnapshot, check_quota

def quota(remain, codes=()): return QuotaSnapshot(1, remain, [{"code": code} for code in codes])

def test_existing_code_updates_below_quota_floor():
    assert not check_quota(quota(99, ("US.SPY",)), "US.SPY", datetime.now(timezone.utc), []).is_new_code

def test_new_code_is_blocked_by_quota_and_local_limits():
    now = datetime(2026, 7, 17, tzinfo=timezone.utc)
    with pytest.raises(QuotaPolicyError, match="remain_quota"): check_quota(quota(99), "US.SPY", now, [])
    daily = [{"timestamp_utc": now.isoformat(), "code": f"US.X{i}", "is_new_code": True} for i in range(25)]
    with pytest.raises(QuotaPolicyError, match="daily"): check_quota(quota(500), "US.SPY", now, daily)
    rolling = [{"timestamp_utc": (now-timedelta(days=1)).isoformat(), "code": f"US.X{i}", "is_new_code": True} for i in range(200)]
    with pytest.raises(QuotaPolicyError, match="rolling"): check_quota(quota(500), "US.SPY", now, rolling)
