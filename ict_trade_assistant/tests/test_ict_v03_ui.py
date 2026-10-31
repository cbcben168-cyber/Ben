import pandas as pd
import plotly.graph_objects as go
from desk.ict_v03 import scan
from desk.ict_view import add_event_layers, review_text
from test_ict_v03 import history, at


def test_layers_start_at_confirmation_and_never_suggest_live_entry():
    report=scan('US.SPY',history(),at(16,2))
    fig=go.Figure();add_event_layers(fig,report)
    assert fig.data
    for trace in fig.data:
        assert '历史' in trace.name
        for x in trace.x:assert pd.Timestamp(x).tzinfo is not None
    text=review_text(report)
    assert '历史观察' in text and '实时入场建议' in text


def test_unknown_has_no_layers():
    report=scan('US.SPY',pd.DataFrame(),at(16,2))
    fig=go.Figure();add_event_layers(fig,report)
    assert len(fig.data)==0
    assert '不可用' in review_text(report)
