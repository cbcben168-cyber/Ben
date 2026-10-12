from __future__ import annotations

import pandas as pd
import pytest

from factor_research.phase3_edge_engine.contracts import StrategySpec
from factor_research.phase3_edge_engine.simulator import _simulate_one


def _spec() -> StrategySpec:
    return StrategySpec(
        strategy_id="S01",
        variant_id="S01_TEST",
        name_zh="test",
        setup="test",
        trigger="test",
        direction="BOTH",
        entry="NEXT_BAR_OPEN",
        stop="test",
        target="1.5R",
        time_exit_bars=2,
        filter_factor="NONE",
        cost_round_trip_bps=4.0,
        status="TEST",
        attempt_version="TEST",
    )


def test_same_bar_stop_target_is_stop_first_and_does_not_use_full_exit_range():
    frame = pd.DataFrame([
        {"bar_index": 0, "session_date": "2026-01-02", "time_et": pd.Timestamp("2026-01-02 09:35"), "px_open": 100, "px_high": 100, "px_low": 100, "px_close": 100},
        {"bar_index": 1, "session_date": "2026-01-02", "time_et": pd.Timestamp("2026-01-02 09:40"), "px_open": 100, "px_high": 102, "px_low": 98, "px_close": 101},
    ]).set_index("bar_index", drop=False)
    signal = {"bar_index": 0, "session_date": "2026-01-02", "direction": 1, "stop_anchor": 99.0, "target_anchor": float("nan"), "strategy_id": "S01", "signal_id": "x", "signal_time_et": pd.Timestamp("2026-01-02 09:35"), "time_bucket": "09:35-10:30", "premarket_trend": "NEUTRAL", "premarket_vol": "NORMAL", "dynamic_trend": "BULL", "f012_state": "NORMAL", "dynamic_gap": "NO_GAP"}
    trade, decision, exit_index = _simulate_one(frame, signal, _spec())
    assert decision == "TRADED"
    assert exit_index == 1
    assert trade["entry_price"] == 100
    assert trade["target_price"] == 101.5
    assert trade["exit_price"] == 99
    assert trade["exit_reason"] == "AMBIGUOUS_STOP_FIRST"
    assert trade["ambiguous_path"] is True
    assert trade["path_uncertain"] is True
    assert trade["mfe"] == 0.0
    assert trade["net_return"] == pytest.approx(-0.0104)


def test_v311_baseline_replay_matches_frozen_acceptance(phase3_state):
    trades = phase3_state["trades"]
    audit = phase3_state["audit"]
    baseline = trades[trades["variant_id"].isin(["S01_BASE", "S02_BASE", "S03_BASE"])]
    assert baseline.groupby("strategy_id").size().to_dict() == {"S01": 808, "S02": 183, "S03": 81}
    means = baseline.groupby("strategy_id")["net_return"].mean() * 10_000
    assert means["S01"] == pytest.approx(-4.0000107, abs=1e-6)
    assert means["S02"] == pytest.approx(-0.6545163, abs=1e-6)
    assert means["S03"] == pytest.approx(-4.0431963, abs=1e-6)
    busy = audit[(audit["variant_id"] == "S01_BASE") & (audit["decision"] == "POSITION_BUSY")]
    assert len(busy) == 521
    assert not ((audit["strategy_id"] != "S01") & (audit["variant_id"].str.endswith("_BASE")) & (audit["decision"] == "POSITION_BUSY")).any()


def test_filtered_replay_releases_positions_and_reconsiders_busy_signals(phase3_state):
    audit = phase3_state["audit"]
    baseline_busy = set(audit.loc[(audit["variant_id"] == "S01_BASE") & (audit["decision"] == "POSITION_BUSY"), "signal_id"])
    filtered_traded = set(audit.loc[(audit["variant_id"] == "S01_F036") & (audit["decision"] == "TRADED"), "signal_id"])
    assert len(baseline_busy & filtered_traded) == 57


def test_trade_cost_and_entry_time_contract(phase3_state):
    trades = phase3_state["trades"]
    assert ((trades["gross_return"] - trades["net_return"] - 0.0004).abs() < 1e-12).all()
    assert (pd.to_datetime(trades["entry_observed_at_et"]) - pd.to_datetime(trades["entry_time_et"]) == pd.Timedelta(minutes=5)).all()
    assert (pd.to_datetime(trades["entry_time_et"]) == pd.to_datetime(trades["signal_time_et"])).all()
