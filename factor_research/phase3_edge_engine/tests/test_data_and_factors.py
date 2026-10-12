from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from factor_research.phase3_edge_engine.contracts import EARLY_CLOSES
from factor_research.phase3_edge_engine.factors import build_features, compute_factor_matrix
from factor_research.phase3_edge_engine.pipeline import DEFAULT_DATA


def test_cache_gate_and_frozen_coverage(phase3_state):
    qualification = phase3_state["qualification"]
    assert qualification["status"] == "PASS_5M_ONLY"
    assert qualification["bars"] == 19_470
    assert qualification["sessions"] == 251
    assert qualification["train_sessions"] == 187
    assert qualification["one_minute_status"] == "NOT_AVAILABLE_NOT_REQUIRED"
    assert qualification["volume_status"] == "PROHIBITED"
    assert qualification["cache_hit"] is True


def test_rth_grid_and_half_days_are_exact(phase3_state):
    features = phase3_state["features"]
    counts = features.groupby("session_date").size()
    assert set(counts[counts == 42].index) == EARLY_CLOSES
    assert (counts.drop(index=list(EARLY_CLOSES)) == 78).all()
    half_day = features[features["session_date"] == "2025-11-28"]
    assert half_day["clock"].iloc[-1] == "13:00"
    assert not (half_day["time_bucket"] == "14:00-15:55").any()


def test_future_returns_never_cross_sessions(phase3_state):
    features = phase3_state["features"]
    for _, day in features.groupby("session_date"):
        assert day["return_h12"].tail(12).isna().all()
        if len(day) > 12:
            assert day["return_h12"].iloc[:-12].notna().all()


def test_forward_adjustment_matches_frozen_rehab_contract(phase3_state):
    raw = phase3_state["raw"]
    adjusted = phase3_state["features"]
    rehab = pd.read_csv(DEFAULT_DATA.with_name("opend_rehab.csv"))
    for event in rehab.itertuples(index=False):
        before_index = adjusted.index[adjusted["session_date"] < event.ex_div_date][-1]
        current_index = adjusted.index[adjusted["session_date"] == event.ex_div_date][0]
        observed_ratio = adjusted.at[before_index, "px_close"] / adjusted.at[current_index, "px_close"]
        expected_ratio = (
            event.forward_adj_factor_a * raw.at[before_index, "close"] + event.forward_adj_factor_b
        ) / raw.at[current_index, "close"]
        assert observed_ratio == pytest.approx(expected_ratio, abs=1e-12)


def test_all_36_frozen_formulas_are_implemented(phase3_state):
    matrix = phase3_state["matrix"]
    specs = phase3_state["factor_specs"]
    assert list(matrix.columns) == [item.factor_id for item in specs]
    assert matrix.shape == (19_470, 36)
    assert set(np.unique(matrix.to_numpy())).issubset({-1, 0, 1})
    assert matrix["F011"].ne(0).groupby(phase3_state["features"]["session_date"]).sum().max() <= 1


def test_factor_engine_has_no_future_data_dependency(phase3_state):
    raw = phase3_state["raw"].copy()
    original = phase3_state["matrix"]
    cutoff = len(raw) - 20
    raw.loc[cutoff:, ["open", "high", "low", "close"]] *= 1.25
    mutated_features = build_features(raw, DEFAULT_DATA.with_name("opend_rehab.csv"))
    mutated = compute_factor_matrix(mutated_features)
    pd.testing.assert_frame_equal(original.iloc[:cutoff], mutated.iloc[:cutoff])


def test_frozen_f001_and_f006_formulas(phase3_state):
    features = phase3_state["features"]
    matrix = phase3_state["matrix"]
    assert (matrix["F001"].eq(1) == (features["px_close"] > features["ema20"])).all()
    candle_range = features["px_high"] - features["px_low"]
    expected = (
        (features["px_close"] > features["px_open"])
        & (candle_range > 0)
        & ((features["px_close"] - features["px_open"]) / candle_range > 0.60)
    )
    assert (matrix["F006"].eq(1) == expected).all()
