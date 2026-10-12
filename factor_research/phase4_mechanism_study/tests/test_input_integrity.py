from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from factor_research.phase4_mechanism_study.contracts import ADJUSTMENT_BASIS, SessionSpec
from factor_research.phase4_mechanism_study.input_integrity import (
    ANCHOR_ADJUSTED_CLOSE,
    EXPECTED_REHAB_ROWS,
    EXPECTED_TRAIN_AFFECTED_ROWS,
    PRICE_COLUMNS,
    RAW_BASIS,
    InputIntegrityError,
    RehabEvent,
    apply_dynamic_forward_adjustments,
    qualify_authorized_train_repaired,
    validate_adjusted_frame,
    validate_qualified_derivations,
    validate_rehab_frame,
)
from factor_research.phase4_mechanism_study.mechanisms import scan_all
from factor_research.phase4_mechanism_study.volatility import expected_bar_ends, qualify_ohlc

from .conftest import synthetic_frame, synthetic_schedule


def _raw(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "session_date": day,
                "time_et": f"09:{35 + index * 5:02d}",
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "source_adjustment_basis": RAW_BASIS,
            }
            for index, (day, open_, high, low, close) in enumerate(rows)
        ]
    )


def _rehab(rows=EXPECTED_REHAB_ROWS) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["ex_div_date", "forward_adj_factor_a", "forward_adj_factor_b", "per_cash_div"],
    )


def _real_inputs() -> tuple[Path, Path]:
    root = Path(__file__).resolve().parents[3]
    audit = root / "factor_research" / "spy_factor_batch_v1" / "validation" / "train_ema_supplement_7514881494081894629"
    return audit / "opend_5m_ohlc.csv", audit / "manifest.json"


def test_unadjusted_and_label_only_data_gate_fail_closed() -> None:
    raw = _raw([("2026-06-17", 740.0, 742.0, 739.0, 740.96)])
    events = (RehabEvent("2026-06-18", 0.99743, 0.0, 1.90352),)
    labeled_only = raw.copy()
    labeled_only["adjustment_basis"] = ADJUSTMENT_BASIS
    with pytest.raises(InputIntegrityError, match="LABEL_ONLY_ADJUSTMENT"):
        validate_adjusted_frame(raw, labeled_only, events)


def test_complete_adjustment_passes_and_changes_all_ohlc_columns() -> None:
    raw = _raw([("2026-06-17", 740.0, 742.0, 739.0, 740.96)])
    events = (RehabEvent("2026-06-18", 0.99743, 0.0, 1.90352),)
    adjusted, audit = apply_dynamic_forward_adjustments(raw, events)
    validate_adjusted_frame(raw, adjusted, events)
    assert audit[0]["affected_rows"] == 1
    for column in PRICE_COLUMNS:
        assert adjusted.loc[0, column] == pytest.approx(raw.loc[0, column] * 0.99743, abs=1e-12)


def test_phase3_cross_check_mismatch_fails_closed() -> None:
    raw = _raw([("2026-06-17", 740.0, 742.0, 739.0, 740.96)])
    events = (RehabEvent("2026-06-18", 0.99743, 0.0, 1.90352),)
    adjusted, _ = apply_dynamic_forward_adjustments(raw, events)
    reference = pd.DataFrame(
        {f"px_{column}": adjusted[column].astype(float) for column in PRICE_COLUMNS}
    )
    reference.loc[0, "px_close"] += 1e-6
    with pytest.raises(InputIntegrityError, match="PHASE3_ADJUSTMENT_PARITY_MISMATCH"):
        validate_adjusted_frame(raw, adjusted, events, phase3_reference=reference)


def test_partial_ohlc_adjustment_fails_closed() -> None:
    raw = _raw([("2026-06-17", 740.0, 742.0, 739.0, 740.96)])
    events = (RehabEvent("2026-06-18", 0.99743, 0.0, 1.90352),)
    adjusted, _ = apply_dynamic_forward_adjustments(raw, events)
    adjusted.loc[0, "high"] = raw.loc[0, "high"]
    with pytest.raises(InputIntegrityError, match="NUMERIC_ADJUSTMENT_MISMATCH"):
        validate_adjusted_frame(raw, adjusted, events)


def test_multiple_events_accumulate_in_date_order_with_strict_boundaries() -> None:
    raw = _raw(
        [
            ("2025-12-18", 100.0, 110.0, 90.0, 105.0),
            ("2025-12-19", 200.0, 210.0, 190.0, 205.0),
            ("2026-03-20", 300.0, 310.0, 290.0, 305.0),
        ]
    )
    events = (
        RehabEvent("2025-12-19", 0.5, 1.0, 0.0),
        RehabEvent("2026-03-20", 0.8, 2.0, 0.0),
    )
    adjusted, audit = apply_dynamic_forward_adjustments(raw, events)
    assert adjusted.loc[0, "close"] == (105.0 * 0.5 + 1.0) * 0.8 + 2.0
    assert adjusted.loc[1, "close"] == 205.0 * 0.8 + 2.0
    assert adjusted.loc[2, "close"] == 305.0
    assert tuple(item["affected_rows"] for item in audit) == (1, 2)


def test_reapplying_to_adjusted_input_fails() -> None:
    raw = _raw([("2026-06-17", 100.0, 101.0, 99.0, 100.0)])
    events = (RehabEvent("2026-06-18", 0.9, 0.0, 0.0),)
    adjusted, _ = apply_dynamic_forward_adjustments(raw, events)
    with pytest.raises(InputIntegrityError, match="ALREADY_ADJUSTED_INPUT"):
        apply_dynamic_forward_adjustments(adjusted, events)


def test_missing_duplicate_and_invalid_rehab_rows_fail_closed() -> None:
    with pytest.raises(InputIntegrityError, match="REHAB_MISSING_EVENT"):
        validate_rehab_frame(_rehab(EXPECTED_REHAB_ROWS[:-1]))
    duplicate = _rehab((*EXPECTED_REHAB_ROWS, EXPECTED_REHAB_ROWS[-1]))
    with pytest.raises(InputIntegrityError, match="REHAB_DUPLICATE_EVENT"):
        validate_rehab_frame(duplicate)
    invalid = _rehab()
    invalid.loc[0, "forward_adj_factor_a"] = 0.0
    with pytest.raises(InputIntegrityError, match="REHAB_INVALID_FACTOR_A"):
        validate_rehab_frame(invalid)


def test_appending_future_bars_does_not_change_adjusted_prefix() -> None:
    prefix = _raw(
        [
            ("2026-06-17", 100.0, 101.0, 99.0, 100.0),
            ("2026-06-18", 101.0, 102.0, 100.0, 101.0),
        ]
    )
    extended = pd.concat(
        [prefix, _raw([("2026-06-19", 102.0, 103.0, 101.0, 102.0)])],
        ignore_index=True,
    )
    events = (RehabEvent("2026-06-18", 0.99743, 0.0, 1.90352),)
    prefix_adjusted, _ = apply_dynamic_forward_adjustments(prefix, events)
    extended_adjusted, _ = apply_dynamic_forward_adjustments(extended, events)
    pd.testing.assert_frame_equal(prefix_adjusted, extended_adjusted.iloc[: len(prefix)].reset_index(drop=True))


def test_appending_future_session_does_not_change_prior_asof_scan() -> None:
    short_schedule = synthetic_schedule(22)
    long_schedule = synthetic_schedule(23)
    event = (RehabEvent("2025-12-19", 0.5, 0.0, 0.0),)

    def adjusted_data(schedule):
        frame = synthetic_frame(schedule).drop(columns="adjustment_basis")
        frame["source_adjustment_basis"] = RAW_BASIS
        adjusted, _ = apply_dynamic_forward_adjustments(frame, event)
        return qualify_ohlc(
            adjusted[["session_date", "time_et", *PRICE_COLUMNS, "adjustment_basis"]],
            schedule,
            expected_session_count=len(schedule),
        )

    day = short_schedule[-1].session_date
    assert scan_all(adjusted_data(short_schedule), day) == scan_all(adjusted_data(long_schedule), day)


def test_gap_uses_same_adjusted_basis_at_event_boundary() -> None:
    schedule = [SessionSpec("2026-06-17", "16:00"), SessionSpec("2026-06-18", "16:00")]
    rows = []
    for spec in schedule:
        for time_et in expected_bar_ends(spec.close_time_et):
            rows.append((spec.session_date, time_et))
    raw = pd.DataFrame(
        {
            "session_date": [item[0] for item in rows],
            "time_et": [item[1] for item in rows],
            "open": 741.0,
            "high": 742.0,
            "low": 739.0,
            "close": 740.96,
            "source_adjustment_basis": RAW_BASIS,
        }
    )
    events = (RehabEvent("2026-06-18", 0.99743, 0.0, 1.90352),)
    adjusted, _ = apply_dynamic_forward_adjustments(raw, events)
    qualified = qualify_ohlc(
        adjusted[["session_date", "time_et", *PRICE_COLUMNS, "adjustment_basis"]],
        schedule,
        expected_session_count=2,
    )
    assert qualified.daily.loc["2026-06-18", "previous_close"] == pytest.approx(
        ANCHOR_ADJUSTED_CLOSE, abs=1e-12
    )
    assert qualified.daily.loc["2026-06-18", "open"] == 741.0


def test_atr_and_daily_atr_are_recomputed_from_adjusted_ohlc() -> None:
    schedule = synthetic_schedule(22)
    frame = synthetic_frame(schedule).drop(columns="adjustment_basis")
    frame["source_adjustment_basis"] = RAW_BASIS
    events = (RehabEvent("2025-12-19", 0.5, 0.0, 0.0),)
    adjusted, _ = apply_dynamic_forward_adjustments(frame, events)
    qualified = qualify_ohlc(
        adjusted[["session_date", "time_et", *PRICE_COLUMNS, "adjustment_basis"]],
        schedule,
        expected_session_count=22,
    )
    assert qualified.bars.loc[20, "intraday_atr20"] == pytest.approx(0.5)
    assert qualified.daily.iloc[21]["daily_atr20"] == pytest.approx(0.5)


def test_wrong_qualified_price_or_volatility_basis_fails_closed() -> None:
    schedule = synthetic_schedule(22)
    raw = synthetic_frame(schedule).drop(columns="adjustment_basis")
    raw["source_adjustment_basis"] = RAW_BASIS
    adjusted, _ = apply_dynamic_forward_adjustments(
        raw, (RehabEvent("2025-12-19", 0.5, 0.0, 0.0),)
    )
    qualified = qualify_ohlc(
        adjusted[["session_date", "time_et", *PRICE_COLUMNS, "adjustment_basis"]],
        schedule,
        expected_session_count=22,
    )

    bad_bars = qualified.bars.copy()
    bad_bars.loc[0, "close"] += 1.0
    with pytest.raises(InputIntegrityError, match="QUALIFIED_PRICE_BASIS_MISMATCH"):
        validate_qualified_derivations(adjusted, replace(qualified, bars=bad_bars))

    bad_bars = qualified.bars.copy()
    bad_bars.loc[20, "intraday_atr20"] += 1.0
    with pytest.raises(InputIntegrityError, match="INTRADAY_VOLATILITY_BASIS_MISMATCH"):
        validate_qualified_derivations(adjusted, replace(qualified, bars=bad_bars))

    bad_daily = qualified.daily.copy()
    bad_daily.iloc[-1, bad_daily.columns.get_loc("previous_close")] += 1.0
    with pytest.raises(InputIntegrityError, match="DAILY_VOLATILITY_BASIS_MISMATCH"):
        validate_qualified_derivations(adjusted, replace(qualified, daily=bad_daily))

    bad_daily = qualified.daily.copy()
    bad_daily.iloc[-1, bad_daily.columns.get_loc("daily_atr20")] += 1.0
    with pytest.raises(InputIntegrityError, match="DAILY_VOLATILITY_BASIS_MISMATCH"):
        validate_qualified_derivations(adjusted, replace(qualified, daily=bad_daily))


def test_frozen_raw_file_hash_drift_fails_before_adjustment(tmp_path: Path) -> None:
    data_path, manifest_path = _real_inputs()
    copied_data = tmp_path / data_path.name
    copied_manifest = tmp_path / manifest_path.name
    copied_rehab = tmp_path / "opend_rehab.csv"
    shutil.copy2(data_path, copied_data)
    shutil.copy2(manifest_path, copied_manifest)
    shutil.copy2(manifest_path.with_name("opend_rehab.csv"), copied_rehab)
    copied_data.write_bytes(copied_data.read_bytes() + b"\n")
    with pytest.raises(InputIntegrityError, match="FROZEN_DATA_HASH_MISMATCH"):
        qualify_authorized_train_repaired(copied_data, copied_manifest)


def test_real_data_gate_verifies_four_events_phase3_parity_and_no_pretrain_warmup() -> None:
    data_path, manifest_path = _real_inputs()
    qualified, report = qualify_authorized_train_repaired(data_path, manifest_path)
    assert report["status"] == "DATA_GATE_PASS_NUMERIC_ADJUSTMENT_VERIFIED"
    assert report["phase3_cross_check"] == "EXACT_ARRAY_MATCH"
    assert tuple(item["affected_rows"] for item in report["rehab_events"]) == EXPECTED_TRAIN_AFFECTED_ROWS
    assert report["m06_anchor"]["adjusted_close"] == pytest.approx(ANCHOR_ADJUSTED_CLOSE, abs=1e-12)
    assert qualified.bars["session_date"].min() == "2025-10-01"
    assert qualified.bars["session_date"].max() == "2026-06-30"
    assert report["as_of_contract"]["pre_train_price_warmup"] is False
    assert report["as_of_contract"]["post_train_rehab_events"] == 0
    assert np.isfinite(qualified.bars[["intraday_tr", "intraday_atr20"]].iloc[20:].to_numpy()).all()
