from dataclasses import replace
from datetime import UTC, datetime

import plotly.graph_objects as go
import pandas as pd

from tv_quant.pattern_finder.charts import build_candlestick_figure
from tv_quant.pattern_finder.flat_base import detect_flat_base
from tv_quant.pattern_finder.fixtures import load_fixture
from tv_quant.pattern_finder.models import ChartSeries, DailyBar


def _real_series() -> ChartSeries:
    bars = (
        DailyBar(
            timestamp_utc=datetime(2026, 8, 6, tzinfo=UTC),
            open=201.0,
            high=203.0,
            low=200.0,
            close=202.0,
            volume=1_000_001,
        ),
        DailyBar(
            timestamp_utc=datetime(2026, 8, 7, tzinfo=UTC),
            open=202.0,
            high=204.0,
            low=201.0,
            close=203.0,
            volume=1_000_002,
        ),
    )
    return ChartSeries(symbol="AAPL", label="Futu QFQ daily", bars=bars)


def test_chart_uses_fixture_dates_and_ohlcv_values() -> None:
    fixture = load_fixture("TEST_FLAT")
    figure = build_candlestick_figure(fixture)

    assert isinstance(figure, go.Figure)
    assert len(figure.data) == 2
    price, volume = figure.data
    assert price.type == "candlestick"
    assert price.name == "日K（OHLC）"
    assert tuple(price.x) == tuple(bar.timestamp_utc for bar in fixture.bars)
    assert tuple(price.open) == tuple(bar.open for bar in fixture.bars)
    assert tuple(price.high) == tuple(bar.high for bar in fixture.bars)
    assert tuple(price.low) == tuple(bar.low for bar in fixture.bars)
    assert tuple(price.close) == tuple(bar.close for bar in fixture.bars)
    assert volume.type == "bar"
    assert volume.name == "成交量"
    assert tuple(volume.y) == tuple(bar.volume for bar in fixture.bars)


def test_chart_has_two_rows_and_interactive_zoom() -> None:
    figure = build_candlestick_figure(load_fixture("TEST_ROUNDED"))

    assert figure.data[0].yaxis == "y"
    assert figure.data[1].yaxis == "y2"
    assert figure.layout.dragmode == "zoom"
    assert figure.layout.xaxis.rangeslider.visible is False
    assert figure.layout.hovermode == "x unified"


def test_chart_marks_base_window_support_and_resistance() -> None:
    fixture = load_fixture("TEST_READY")
    figure = build_candlestick_figure(fixture)
    shapes = {shape.name: shape for shape in figure.layout.shapes}

    assert set(shapes) == {"底部区间", "支撑位", "阻力位"}
    assert shapes["底部区间"].type == "rect"
    assert shapes["底部区间"].x0 == fixture.base_start
    assert shapes["底部区间"].x1 == fixture.base_end
    assert shapes["支撑位"].type == "line"
    assert shapes["支撑位"].y0 == fixture.support
    assert shapes["支撑位"].y1 == fixture.support
    assert shapes["阻力位"].type == "line"
    assert shapes["阻力位"].y0 == fixture.resistance
    assert shapes["阻力位"].y1 == fixture.resistance
    assert {annotation.text for annotation in figure.layout.annotations} == {
        "底部区间",
        "支撑位",
        "阻力位",
    }


def test_real_chart_uses_literal_daily_bars_without_detector_overlays() -> None:
    series = _real_series()

    figure = build_candlestick_figure(series)

    assert len(figure.data) == 2
    assert tuple(figure.data[0].close) == (202.0, 203.0)
    assert tuple(figure.data[1].y) == (1_000_001, 1_000_002)
    assert tuple(figure.layout.shapes) == ()
    assert tuple(figure.layout.annotations) == ()
    assert figure.layout.title.text == "AAPL — Futu 前复权日线"


def _fixture_detection(symbol: str):
    fixture = load_fixture(symbol)
    frame = pd.DataFrame(
        {
            "timestamp_utc": [bar.timestamp_utc for bar in fixture.bars],
            "ticker": [symbol] * len(fixture.bars),
            "open": [bar.open for bar in fixture.bars],
            "high": [bar.high for bar in fixture.bars],
            "low": [bar.low for bar in fixture.bars],
            "close": [bar.close for bar in fixture.bars],
            "volume": [bar.volume for bar in fixture.bars],
        }
    )
    return fixture, detect_flat_base(frame)


def test_chart_uses_detector_selected_flat_base_overlays() -> None:
    fixture, result = _fixture_detection("TEST_FLAT")

    figure = build_candlestick_figure(fixture, flat_base=result)
    shapes = {shape.name: shape for shape in figure.layout.shapes}

    assert result.pattern_flat_base is True
    assert shapes["底部区间"].x0 == result.selected.base_start
    assert shapes["底部区间"].x1 == result.selected.base_end
    assert shapes["支撑位"].y0 == result.selected.support_level
    assert shapes["阻力位"].y0 == result.selected.resistance_level


def test_chart_hides_detector_overlays_for_flat_base_no() -> None:
    fixture, result = _fixture_detection("TEST_FLAT")
    rejected = replace(result, pattern_flat_base=False)

    figure = build_candlestick_figure(fixture, flat_base=rejected)

    assert tuple(figure.layout.shapes) == ()
    assert tuple(figure.layout.annotations) == ()
