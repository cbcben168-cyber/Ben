from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .flat_base import FlatBaseResult
from .models import ChartFixture, ChartSeries


def build_candlestick_figure(
    series: ChartFixture | ChartSeries,
    *,
    flat_base: FlatBaseResult | None = None,
) -> go.Figure:
    timestamps = tuple(bar.timestamp_utc for bar in series.bars)
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=(0.75, 0.25),
    )
    figure.add_trace(
        go.Candlestick(
            name="日K（OHLC）",
            x=timestamps,
            open=tuple(bar.open for bar in series.bars),
            high=tuple(bar.high for bar in series.bars),
            low=tuple(bar.low for bar in series.bars),
            close=tuple(bar.close for bar in series.bars),
        ),
        row=1,
        col=1,
    )
    figure.add_trace(
        go.Bar(
            name="成交量",
            x=timestamps,
            y=tuple(bar.volume for bar in series.bars),
            marker_color="#64748b",
        ),
        row=2,
        col=1,
    )

    detector_overlay = flat_base is not None and flat_base.pattern_flat_base
    legacy_fixture_overlay = flat_base is None and isinstance(series, ChartFixture)
    if detector_overlay or legacy_fixture_overlay:
        if detector_overlay:
            selected = flat_base.selected
            base_start = selected.base_start
            base_end = selected.base_end
            support = selected.support_level
            resistance = selected.resistance_level
        else:
            base_start = series.base_start
            base_end = series.base_end
            support = series.support
            resistance = series.resistance
        figure.add_shape(
            name="底部区间",
            type="rect",
            x0=base_start,
            x1=base_end,
            y0=0,
            y1=1,
            xref="x",
            yref="y domain",
            fillcolor="#f59e0b",
            opacity=0.12,
            line_width=0,
            layer="below",
        )
        for name, value, color in (
            ("支撑位", support, "#16a34a"),
            ("阻力位", resistance, "#dc2626"),
        ):
            figure.add_shape(
                name=name,
                type="line",
                x0=timestamps[0],
                x1=timestamps[-1],
                y0=value,
                y1=value,
                xref="x",
                yref="y",
                line={"color": color, "dash": "dash", "width": 1.5},
            )
        for text, x, y, yshift, xanchor in (
            (
                "底部区间",
                base_start + (base_end - base_start) / 2,
                resistance,
                12,
                "center",
            ),
            ("支撑位", timestamps[-1], support, -12, "right"),
            ("阻力位", timestamps[-1], resistance, 12, "right"),
        ):
            figure.add_annotation(
                text=text,
                x=x,
                y=y,
                xref="x",
                yref="y",
                showarrow=False,
                xanchor=xanchor,
                yshift=yshift,
            )
    figure.update_layout(
        title=f"{series.symbol} — "
        f"{series.pattern_label if isinstance(series, ChartFixture) else 'Futu 前复权日线'}",
        dragmode="zoom",
        hovermode="x unified",
        height=720,
        margin={"l": 45, "r": 25, "t": 55, "b": 35},
        showlegend=True,
        xaxis_rangeslider_visible=False,
    )
    figure.update_yaxes(title_text="价格", row=1, col=1)
    figure.update_yaxes(title_text="成交量", row=2, col=1)
    figure.update_xaxes(title_text="日期", row=2, col=1)
    return figure
