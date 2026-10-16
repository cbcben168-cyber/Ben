from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_research.factor_scout_v1.core import (
    FACTORS,
    RunCounters,
    ScoutBlocked,
    _screen_status,
    compute_forward_responses,
    compute_shared_features,
    load_registry,
    qualify_ohlc,
    run_screen,
)
from factor_research.factor_scout_v1.screen import ROOT, build_synthetic_ohlc, write_outputs


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_six_factor_registry_loads_and_identities_match() -> None:
    registry = load_registry(ROOT / "FACTOR_REGISTRY.csv")
    assert tuple(registry["factor_id"]) == tuple(f.factor_id for f in FACTORS)
    repo = ROOT.parents[1]
    for row in registry.itertuples(index=False):
        assert _sha256(repo / row.formula_source_path) == row.formula_source_sha256
        assert _sha256(repo / row.implementation_source_path) == row.implementation_source_sha256


def test_frozen_formulas_and_threshold_boundaries_are_loaded_without_redefinition() -> None:
    row = pd.Series(
        {
            "close": 110.0,
            "session_open": 100.0,
            "daily_atr20": 20.0,
            "daily_range_so_far": 7.0,
            "directional_efficiency": 0.60,
            "prev_close_location": 0.75,
            "prev_day_range": 25.0,
            "prev_daily_atr20": 20.0,
            "range_position": 0.75,
        }
    )
    expected = {"F01": 0.5, "F02": 0.35, "F03": 0.60, "F04": 0.75, "F05": 1.25, "F06": 0.75}
    for factor in FACTORS:
        value = factor.value(row)
        assert value == pytest.approx(expected[factor.factor_id])
        assert factor.exposed(value)


def test_future_bars_do_not_change_anchor_signal() -> None:
    raw = build_synthetic_ohlc()
    _results, original = run_screen(raw)
    target_day = raw["session_date"].iloc[-1]
    anchor_utc = pd.Timestamp(f"{target_day} 10:00", tz="America/New_York").tz_convert("UTC")
    changed = raw.copy()
    future = changed["timestamp_utc"] > anchor_utc
    changed.loc[future, ["open", "high", "low", "close"]] *= 1.5
    changed.loc[future, "high"] = changed.loc[future, ["open", "high", "close"]].max(axis=1)
    changed.loc[future, "low"] = changed.loc[future, ["open", "low", "close"]].min(axis=1)
    _results, revised = run_screen(changed)
    key = lambda frame: frame.loc[
        frame["factor_id"].eq("F01") & frame["session_date"].eq(target_day),
        ["factor_value", "exposed"],
    ].reset_index(drop=True)
    pd.testing.assert_frame_equal(key(original), key(revised))


def test_previous_complete_day_is_visible_but_unfinished_current_day_is_not_daily_input() -> None:
    raw = build_synthetic_ohlc()
    last_day = raw["session_date"].iloc[-1]
    current = raw["session_date"].eq(last_day)
    truncated = raw.loc[~current | (raw["timestamp_utc"].dt.tz_convert("America/New_York").dt.strftime("%H:%M") <= "10:00")].copy()
    truncated.loc[truncated["session_date"].eq(last_day), "session_complete"] = False
    prepared = compute_shared_features(qualify_ohlc(truncated))
    current_anchor = prepared.loc[
        prepared["session_date"].eq(last_day) & prepared["time_et"].eq("10:00")
    ].iloc[0]
    prior_day = raw.loc[raw["session_date"].ne(last_day), "session_date"].iloc[-1]
    prior = raw.loc[raw["session_date"].eq(prior_day)]
    expected = (prior["close"].iloc[-1] - prior["low"].min()) / (prior["high"].max() - prior["low"].min())
    assert current_anchor["prev_close_location"] == pytest.approx(expected)
    assert np.isfinite(current_anchor["daily_atr20"])


def test_six_bar_boundary_and_cross_session_are_fail_closed() -> None:
    raw = build_synthetic_ohlc()
    qualified = qualify_ohlc(raw)
    prepared = compute_forward_responses(compute_shared_features(qualified))
    last_day = prepared["session_date"].iloc[-1]
    valid = prepared.loc[prepared["session_date"].eq(last_day) & prepared["time_et"].eq("15:30")].iloc[0]
    invalid = prepared.loc[prepared["session_date"].eq(last_day) & prepared["time_et"].eq("15:35")].iloc[0]
    assert bool(valid["forward_valid"])
    assert not bool(invalid["forward_valid"])


def test_frozen_xnys_early_close_grid_is_accepted_without_fabricated_bars() -> None:
    raw = build_synthetic_ohlc(session_count=1)
    session_date = raw["session_date"].iloc[0]
    local_time = raw["timestamp_utc"].dt.tz_convert("America/New_York").dt.strftime("%H:%M")
    early = raw.loc[local_time.le("13:00")].copy()
    qualified = qualify_ohlc(early, session_close_by_date={session_date: "13:00"})
    assert len(qualified) == 42
    assert qualified.iloc[-1]["time_et"] == "13:00"


def test_train_classification_rules_are_fixed_before_real_screen() -> None:
    assert _screen_status(
        events=49,
        unique_days=49,
        lift_vs_baseline=1.0,
        early_lift=1.0,
        late_lift=1.0,
        max_overlap=0.0,
    )[0] == "WATCH_CAPACITY"
    assert _screen_status(
        events=50,
        unique_days=40,
        lift_vs_baseline=1.0,
        early_lift=1.0,
        late_lift=-0.1,
        max_overlap=0.0,
    )[0] == "WATCH_UNSTABLE"
    assert _screen_status(
        events=50,
        unique_days=40,
        lift_vs_baseline=1.0,
        early_lift=1.0,
        late_lift=1.0,
        max_overlap=0.80,
    )[0] == "WATCH_OVERLAP"
    assert _screen_status(
        events=50,
        unique_days=40,
        lift_vs_baseline=1.0,
        early_lift=1.0,
        late_lift=1.0,
        max_overlap=0.79,
    )[0] == "KEEP_FOR_DEEP_TEST"


def test_direction_and_volatility_use_different_response_units() -> None:
    results, observations = run_screen(build_synthetic_ohlc())
    assert results.set_index("factor_id").loc["F01", "baseline_definition"].endswith("basis_points")
    assert results.set_index("factor_id").loc["F02", "baseline_definition"].endswith("unannualized_realized_volatility")
    assert results.set_index("factor_id").loc["F04", "baseline_definition"].endswith("basis_points")
    assert results.set_index("factor_id").loc["F05", "baseline_definition"].endswith("unannualized_realized_volatility")
    f02 = observations.loc[observations["factor_id"].eq("F02") & observations["status"].eq("OK")]
    assert (f02["forward_realized_volatility"] >= 0).all()


def test_zero_events_and_warmup_shortfall_still_produce_rows() -> None:
    short = build_synthetic_ohlc(session_count=1)
    short.loc[:, ["open", "close"]] = 100.0
    short.loc[:, "high"] = 100.05
    short.loc[:, "low"] = 99.95
    results, _observations = run_screen(short)
    assert tuple(results["factor_id"]) == tuple(f.factor_id for f in FACTORS)
    assert (results["events"] == 0).all()
    assert (results.set_index("factor_id").loc[["F01", "F02", "F05"], "excluded_count"] > 0).all()


@pytest.mark.parametrize("mode", ["missing", "pit"])
def test_missing_input_or_unqualified_pit_blocks(mode: str) -> None:
    raw = build_synthetic_ohlc()
    if mode == "missing":
        raw = raw.drop(columns="high")
        match = "BLOCKED_DATA"
    else:
        raw.loc[0, "bar_available_at_utc"] = raw.loc[0, "timestamp_utc"] + pd.Timedelta(seconds=1)
        match = "BLOCKED_PIT"
    with pytest.raises(ScoutBlocked, match=match):
        run_screen(raw)


def test_all_factors_share_one_feature_and_forward_pass() -> None:
    counters = RunCounters()
    results, _observations = run_screen(build_synthetic_ohlc(), counters)
    assert len(results) == 6
    assert counters == RunCounters(data_reads=1, feature_passes=1, forward_passes=1)


def test_synthetic_baseline_and_event_mean_can_be_recomputed() -> None:
    results, observations = run_screen(build_synthetic_ohlc())
    row = results.set_index("factor_id").loc["F01"]
    eligible = observations.loc[observations["factor_id"].eq("F01") & observations["status"].eq("OK")]
    events = eligible.loc[eligible["exposed"]]
    independent = (events["effect_sign"] * events["forward_raw_return"] * 10_000.0).mean()
    if events.empty:
        assert pd.isna(row["forward_mean"])
    else:
        assert row["forward_mean"] == pytest.approx(independent)


def test_output_contract_is_synthetic_only(tmp_path: Path) -> None:
    identity = write_outputs(tmp_path)
    expected = {
        "FACTOR_SCREEN_RESULTS.csv", "FACTOR_SHORTLIST.csv", "SCREEN_REPORT.md", "SCREEN_RUN_IDENTITY.json"
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    report = (tmp_path / "SCREEN_REPORT.md").read_text(encoding="utf-8")
    parsed = json.loads((tmp_path / "SCREEN_RUN_IDENTITY.json").read_text(encoding="utf-8"))
    assert identity["evidence_label"] == parsed["evidence_label"] == "SYNTHETIC_DEMO"
    assert parsed["passes"] == {"data_reads": 1, "feature_passes": 1, "forward_passes": 1}
    assert "不能证明交易Edge" in report
    assert not any(label in report for label in ("VALIDATED_EDGE", "OOS_PASS", "LIVE_READY"))
