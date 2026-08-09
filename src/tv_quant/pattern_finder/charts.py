from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .models import ChartFixture, ChartSeries


def build_candlestick_figure(series: ChartFixture | ChartSeries) -> go.Figure:
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
            name="Daily OHLC",
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
            name="Volume",
            x=timestamps,
            y=tuple(bar.volume for bar in series.bars),
            marker_color="#64748b",
        ),
        row=2,
        col=1,
    )

    if isinstance(series, ChartFixture):
        figure.add_shape(
            name="Base Window",
            type="rect",
            x0=series.base_start,
            x1=series.base_end,
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
            ("Support", series.support, "#16a34a"),
            ("Resistance", series.resistance, "#dc2626"),
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
                "Base Window",
                series.base_start + (series.base_end - series.base_start) / 2,
                series.resistance,
                12,
                "center",
            ),
            ("Support", timestamps[-1], series.support, -12, "right"),
            ("Resistance", timestamps[-1], series.resistance, 12, "right"),
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
        f"{series.pattern_label if isinstance(series, ChartFixture) else series.label}",
        dragmode="zoom",
        hovermode="x unified",
        height=720,
        margin={"l": 45, "r": 25, "t": 55, "b": 35},
        showlegend=True,
        xaxis_rangeslider_visible=False,
    )
    figure.update_yaxes(title_text="Price", row=1, col=1)
    figure.update_yaxes(title_text="Volume", row=2, col=1)
    figure.update_xaxes(title_text="Date", row=2, col=1)
    return figure
