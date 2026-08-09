import plotly.graph_objects as go

from tv_quant.pattern_finder.charts import build_candlestick_figure
from tv_quant.pattern_finder.fixtures import load_fixture


def test_chart_uses_fixture_dates_and_ohlcv_values() -> None:
    fixture = load_fixture("TEST_FLAT")
    figure = build_candlestick_figure(fixture)

    assert isinstance(figure, go.Figure)
    assert len(figure.data) == 2
    price, volume = figure.data
    assert price.type == "candlestick"
    assert price.name == "Daily OHLC"
    assert tuple(price.x) == tuple(bar.timestamp_utc for bar in fixture.bars)
    assert tuple(price.open) == tuple(bar.open for bar in fixture.bars)
    assert tuple(price.high) == tuple(bar.high for bar in fixture.bars)
    assert tuple(price.low) == tuple(bar.low for bar in fixture.bars)
    assert tuple(price.close) == tuple(bar.close for bar in fixture.bars)
    assert volume.type == "bar"
    assert volume.name == "Volume"
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

    assert set(shapes) == {"Base Window", "Support", "Resistance"}
    assert shapes["Base Window"].type == "rect"
    assert shapes["Base Window"].x0 == fixture.base_start
    assert shapes["Base Window"].x1 == fixture.base_end
    assert shapes["Support"].type == "line"
    assert shapes["Support"].y0 == fixture.support
    assert shapes["Support"].y1 == fixture.support
    assert shapes["Resistance"].type == "line"
    assert shapes["Resistance"].y0 == fixture.resistance
    assert shapes["Resistance"].y1 == fixture.resistance
    assert {annotation.text for annotation in figure.layout.annotations} == {
        "Base Window",
        "Support",
        "Resistance",
    }
