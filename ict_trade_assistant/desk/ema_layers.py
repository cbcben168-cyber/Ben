"""Historical EMA lines use the unchanged market_state contract at every point."""
from datetime import timedelta

import pandas as pd

from .experiment import BASELINE
from .market_state import market_state

LAYER_MODES = ('不显示指标', '显示当前实验EMA', '对比原始EMA与实验EMA')
UNAVAILABLE = '历史资料不足，暂时无法画出可靠的指标'


def ema_points(frame, period, asof, source, config=BASELINE):
    """Each endpoint reuses the same latest-50-bar initialization and qualification.

    The first 49 candles have no qualified endpoint. Keep at most 50 recent
    endpoints; do not replace the existing rolling sample with full-history EWM.
    """
    current, completed = market_state(frame, period, asof, source, config)
    if current['trend'] == 'UNKNOWN':
        return pd.DataFrame(columns=['ts', 'short', 'long'])
    rows = []
    for end in range(max(50, len(completed)-49), len(completed)+1):
        prefix = completed.iloc[:end]
        cutoff = prefix.closed_at.iloc[-1] + timedelta(minutes=2)
        state, _ = market_state(prefix, period, cutoff, source, config)
        valid = state['trend'] != 'UNKNOWN'
        rows.append(dict(ts=prefix.ts.iloc[-1], short=state.get('ema20') if valid else None,
                         long=state.get('ema50') if valid else None))
    return pd.DataFrame(rows)


def add_ema_lines(fig, points, config, original=False):
    """Only style/label qualified values; manual price layers stay independent."""
    if points.empty:
        return
    for key, span, color in (('short', config.ema_short, '#39d6d0'),
                             ('long', config.ema_long, '#ffb45d')):
        name = ('原始' if original else '实验') + f'EMA{span}'
        fig.add_scatter(x=points.ts.map(str).tolist(), y=points[key].tolist(), name=name,
                        mode='lines+markers' if len(points)==1 else 'lines', marker=dict(size=5),
                        connectgaps=False, opacity=.4 if original else 1.,
                        line=dict(color=color, width=1.5 if original else 2.5,
                                  dash='dash' if original else 'solid'),
                        meta=dict(kind='historical_ema', basis='baseline' if original else 'experiment', span=span),
                        hovertemplate='%{x}<br>'+name+'：%{y:.6f}<extra></extra>')
