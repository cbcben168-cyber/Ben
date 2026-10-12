from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from factor_research.phase4_mechanism_study.contracts import FAMILY, Phase4ContractError
from factor_research.phase4_mechanism_study.statistics import evaluate_family


def _calendar() -> list[str]:
    return list(pd.bdate_range("2025-10-01", periods=187).strftime("%Y-%m-%d"))


def _trades(hypothesis: str, days: list[str], gross_returns: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"hypothesis_id": hypothesis, "session_date": days, "gross_return": gross_returns}
    )


def test_estimand_is_equal_per_trade_not_equal_per_day_and_bootstrap_is_clustered() -> None:
    days = _calendar()
    trades = _trades("P4_M01_ALL", [days[0], days[0], days[1]], [0.0100, 0.0100, -0.0100])
    result = evaluate_family(trades, days)
    row = result.summary.set_index("hypothesis_id").loc["P4_M01_ALL"]
    assert row["mean_net_return_4bp"] == pytest.approx((0.0096 + 0.0096 - 0.0104) / 3)
    assert row["trading_days"] == 2
    assert result.common_indices_sha256 == evaluate_family(trades.iloc[::-1], days).common_indices_sha256


def test_zero_trade_hypotheses_remain_in_complete_holm_family() -> None:
    days = _calendar()
    trades = _trades("P4_M01_ALL", [days[0]], [0.001])
    result = evaluate_family(trades, days)
    summary = result.summary.set_index("hypothesis_id")
    assert tuple(result.summary["hypothesis_id"]) == FAMILY
    assert result.holm_family_size == 3
    assert summary.loc["P4_M02_ALL", "p_value_raw"] == 1.0
    assert summary.loc["P4_M06_ALL", "p_value_raw"] == 1.0
    assert not summary.loc["P4_M02_ALL", "candidate"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_nan_and_infinity_are_illegal_statistical_inputs(bad: float) -> None:
    days = _calendar()
    with pytest.raises(Phase4ContractError, match="NONFINITE_STATISTICAL_INPUT"):
        evaluate_family(_trades("P4_M01_ALL", [days[0]], [bad]), days)


def test_unregistered_hypothesis_and_incomplete_calendar_fail_closed() -> None:
    days = _calendar()
    with pytest.raises(Phase4ContractError, match="INCOMPLETE_OR_UNREGISTERED_FAMILY"):
        evaluate_family(_trades("P4_M99_ALL", [days[0]], [0.01]), days)
    with pytest.raises(Phase4ContractError, match="INVALID_COMMON_DAY_INDEX"):
        evaluate_family(pd.DataFrame(columns=["hypothesis_id", "session_date", "gross_return"]), days[:-1])


def test_simultaneous_interval_is_present_for_full_family_and_candidate_can_pass_synthetic_gate() -> None:
    days = _calendar()
    selected = [days[index] for index in np.linspace(0, 186, 90, dtype=int)]
    returns = [(-0.001 if index % 5 == 0 else 0.004) for index in range(90)]
    result = evaluate_family(_trades("P4_M01_ALL", selected, returns), days)
    row = result.summary.set_index("hypothesis_id").loc["P4_M01_ALL"]
    assert len(result.summary) == 3
    assert {"simultaneous_ci_low", "simultaneous_ci_high"}.issubset(result.summary.columns)
    assert row["simultaneous_ci_low"] > 0
    assert row["p_value_holm"] < 0.05
    assert row["mean_net_return_6bp"] > 0
    assert bool(row["candidate"])


def test_six_bp_nonpositive_mean_blocks_otherwise_eligible_synthetic_result() -> None:
    days = _calendar()
    selected = [days[index] for index in np.linspace(0, 186, 60, dtype=int)]
    gross = [(-0.0001 if index % 6 == 0 else 0.0007) for index in range(60)]
    result = evaluate_family(_trades("P4_M01_ALL", selected, gross), days)
    row = result.summary.set_index("hypothesis_id").loc["P4_M01_ALL"]
    assert row["trade_count"] >= 50 and row["trading_days"] >= 40
    assert row["profit_factor"] > 1.10
    assert row["positive_months"] >= 6
    assert row["max_positive_month_share"] <= 0.40
    assert row["mean_net_return_6bp"] <= 0
    assert not bool(row["candidate"])


def test_month_concentration_gate_rejects_one_dominant_month() -> None:
    days = _calendar()
    selected = days[:50]
    gross = [0.02 if day.startswith("2025-10") else 0.0005 for day in selected]
    result = evaluate_family(_trades("P4_M01_ALL", selected, gross), days)
    row = result.summary.set_index("hypothesis_id").loc["P4_M01_ALL"]
    assert row["max_positive_month_share"] > 0.40
    assert not bool(row["candidate"])
