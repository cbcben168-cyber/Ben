import json

import pytest

from factor_research.spy_factor_batch_v1.train_ema_supplement_audit import (
    EMA_ALPHA,
    Bar,
    RehabEvent,
    build_dynamic_ema_states,
    build_skip_final_ema_states,
    expected_adjusted_prior_close,
    extract_events,
)


def bar(time_key: str, close: float) -> Bar:
    return Bar(time_key, close, close, close, close)


def test_extract_events_reads_unquoted_futu_json_without_csv_reassembly():
    payload = {
        "event_type": "WARMUP_AUDIT",
        "status": "INCOMPLETE",
        "detail": "comma,quote-safe",
    }
    raw = (
        "2025/10/01 21:35:00 (北京),INFO,列印日誌,"
        "FUTU_FACTOR_BATCH_V1|"
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")

    assert extract_events(raw) == [payload]


def test_dynamic_ema_applies_asof_forward_adjustment_before_new_session():
    bars = [
        bar("2025-12-18T15:50:00", 99.0),
        bar("2025-12-18T15:55:00", 100.0),
        bar("2025-12-18T16:00:00", 110.0),
        bar("2025-12-19T09:35:00", 100.0),
        bar("2025-12-19T09:40:00", 101.0),
        bar("2025-12-19T09:45:00", 102.0),
        bar("2025-12-19T09:50:00", 103.0),
    ]
    rehab = [RehabEvent("2025-12-19", 0.9, 1.0, 2.0)]

    states = build_dynamic_ema_states(bars, rehab, start_date="2025-12-18")

    ema_1555 = EMA_ALPHA * 100.0 + (1.0 - EMA_ALPHA) * 99.0
    day_one_ema = EMA_ALPHA * 110.0 + (1.0 - EMA_ALPHA) * ema_1555
    adjusted_ema = 0.9 * day_one_ema + 1.0
    expected = EMA_ALPHA * 100.0 + (1.0 - EMA_ALPHA) * adjusted_ema
    assert states["2025-12-19T09:35:00"].current.ema == pytest.approx(expected)
    assert states["2025-12-19T09:35:00"].previous.close == pytest.approx(100.0)


def test_skip_final_path_omits_regular_and_half_day_close():
    bars = [
        bar("2025-07-02T09:35:00", 100.0),
        bar("2025-07-02T15:55:00", 101.0),
        bar("2025-07-02T16:00:00", 150.0),
        bar("2025-07-03T09:35:00", 102.0),
        bar("2025-07-03T12:55:00", 103.0),
        bar("2025-07-03T13:00:00", 160.0),
        bar("2025-07-07T09:35:00", 104.0),
        bar("2025-07-07T09:40:00", 105.0),
        bar("2025-07-07T09:45:00", 106.0),
        bar("2025-07-07T09:50:00", 107.0),
        bar("2025-07-07T16:00:00", 170.0),
    ]

    states = build_skip_final_ema_states(bars, start_date="2025-07-02")

    assert "2025-07-02T16:00:00" not in states
    assert "2025-07-03T13:00:00" not in states
    assert "2025-07-07T16:00:00" not in states
    assert states["2025-07-07T09:35:00"].current.close == 104.0


def test_select3_expected_close_uses_current_day_rehab_factor():
    adjustment = RehabEvent("2026-03-20", 0.99727, 0.0, 1.797)

    assert expected_adjusted_prior_close(659.8, adjustment) == pytest.approx(657.998746)
    assert expected_adjusted_prior_close(659.8, None) == 659.8
