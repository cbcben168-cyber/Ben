from pathlib import Path

import pytest

from tv_quant.cli import _futu_range, _validate_opend


class Context:
    def __init__(self, response):
        self.response = response

    def get_global_state(self):
        return self.response


def test_opend_state_requires_quote_login_and_ready_status():
    _validate_opend(Context((0, {"qot_logined": "1", "program_status_type": "READY"})), 0, "READY")

    with pytest.raises(RuntimeError, match="请启动 Futu OpenD 并登录"):
        _validate_opend(Context((0, {"qot_logined": "0", "program_status_type": "READY"})), 0, "READY")

    with pytest.raises(RuntimeError, match="status request failed"):
        _validate_opend(Context((1, "connection refused")), 0, "READY")


def test_futu_range_is_ten_years_initially_and_ten_days_incrementally(tmp_path):
    initial_start, initial_end = _futu_range(tmp_path / "SPY_daily.csv")
    assert initial_end.year - initial_start.year == 10
    existing = Path(tmp_path / "SPY_daily.csv")
    existing.touch()
    incremental_start, incremental_end = _futu_range(existing)
    assert (incremental_end - incremental_start).days == 10
