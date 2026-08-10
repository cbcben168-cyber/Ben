from datetime import timedelta

import pandas as pd
import pytest

from tv_quant.pattern_finder.flat_base import detect_flat_base
from tv_quant.pattern_finder.fixtures import load_fixture, load_fixtures


def test_local_fixture_catalog_has_exact_milestone_symbols() -> None:
    fixtures = load_fixtures()

    assert tuple(fixture.symbol for fixture in fixtures) == (
        "TEST_FLAT",
        "TEST_ROUNDED",
        "TEST_READY",
    )


@pytest.mark.parametrize("symbol", ["TEST_FLAT", "TEST_ROUNDED", "TEST_READY"])
def test_fixture_has_160_sorted_valid_daily_bars(symbol: str) -> None:
    fixture = load_fixture(symbol)

    assert len(fixture.bars) == 160
    assert all(bar.timestamp_utc.utcoffset() == timedelta(0) for bar in fixture.bars)
    assert all(bar.timestamp_utc.weekday() < 5 for bar in fixture.bars)
    assert all(
        left.timestamp_utc < right.timestamp_utc
        for left, right in zip(fixture.bars, fixture.bars[1:])
    )
    assert all(bar.low <= min(bar.open, bar.close) for bar in fixture.bars)
    assert all(bar.high >= max(bar.open, bar.close) for bar in fixture.bars)
    assert len({bar.volume for bar in fixture.bars}) > 10


def test_fixture_loads_are_deterministic_and_metadata_is_contained() -> None:
    first = load_fixtures()
    second = load_fixtures()

    assert first == second
    for fixture in first:
        timestamps = {bar.timestamp_utc for bar in fixture.bars}
        assert fixture.base_start in timestamps
        assert fixture.base_end in timestamps
        assert fixture.base_start < fixture.base_end
        assert fixture.support < fixture.resistance


def test_fixture_shapes_are_visually_distinct_without_running_detectors() -> None:
    flat = load_fixture("TEST_FLAT")
    rounded = load_fixture("TEST_ROUNDED")
    ready = load_fixture("TEST_READY")

    flat_closes = [bar.close for bar in flat.bars[-40:]]
    rounded_closes = [bar.close for bar in rounded.bars]
    ready_volumes = [bar.volume for bar in ready.bars]

    assert max(flat_closes) - min(flat_closes) < 2.0
    assert rounded_closes[130] < rounded_closes[100]
    assert rounded_closes[130] < rounded_closes[-1]
    assert 0 < ready.resistance - ready.bars[-1].close < 2.0
    assert sum(ready_volumes[-20:]) < sum(ready_volumes[:20])


def test_unknown_fixture_symbol_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown fixture symbol"):
        load_fixture("AAPL")


def test_test_flat_is_identified_by_detector_logic_not_its_label() -> None:
    fixture = load_fixture("TEST_FLAT")
    frame = pd.DataFrame(
        {
            "timestamp_utc": [bar.timestamp_utc for bar in fixture.bars],
            "ticker": ["TEST_FLAT"] * len(fixture.bars),
            "open": [bar.open for bar in fixture.bars],
            "high": [bar.high for bar in fixture.bars],
            "low": [bar.low for bar in fixture.bars],
            "close": [bar.close for bar in fixture.bars],
            "volume": [bar.volume for bar in fixture.bars],
        }
    )

    result = detect_flat_base(frame)

    assert fixture.pattern_label == "Flat fixture"
    assert result.pattern_flat_base is True
    assert 25 <= result.selected.base_length <= 90
    assert result.selected.base_end == fixture.base_end
