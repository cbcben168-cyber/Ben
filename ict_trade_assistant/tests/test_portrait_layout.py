from pathlib import Path
from unittest.mock import patch
import json
import pandas as pd
from streamlit.testing.v1 import AppTest
from desk.store import Store
from desk.analytics import normalize
from desk.clock import now_et

ROOT=Path(__file__).resolve().parents[1]


def fixture(quality):
    raw=pd.DataFrame(dict(time_key=pd.date_range('2026-10-29 09:30',periods=60,freq='min').astype(str),open=100.,high=101.,low=99.,close=100.,volume=1.))
    return dict(health=dict(quality=quality,reason='隔离布局测试',price=100.,received_at=now_et().isoformat()),minute=normalize(raw,'1M',now_et()),daily=pd.DataFrame(),errors=[])


def test_compact_empty_card_keeps_sop_and_chart_controls(tmp_path):
    store=Store(tmp_path/'layout.db')
    with patch('desk.store.Store',return_value=store),patch('desk.provider.Provider.fetch',return_value=fixture('UNAVAILABLE')):
        app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
        assert not app.exception
        assert not any(r.label=='排序' for r in app.radio)
        sop=next(e for e in app.expander if e.label=='SOP 详细检查与评估依据')
        assert not sop.proto.expanded
        assert any('市场结构转变' in m.value for m in app.markdown)
        assert any('人工目标区' in m.value for m in app.markdown)
        plot=app.get('plotly_chart')[0]
        assert json.loads(plot.proto.spec)['layout']['showlegend'] is False
        app.multiselect(key='price_layers').set_value([]).run()
        assert not app.exception
        assert app.multiselect(key='price_layers').value==[]


def test_four_unique_candidates_not_replaced_by_empty_layout(tmp_path,market_fixture):
    store=Store(tmp_path/'five.db')
    store.save('candidate_atr',.5)
    codes=['US.SPY','US.QQQ','US.IWM','US.SOXX','US.DIA']
    store.save('watchlist',codes)
    store.save('zones',{c:dict(low=99.,high=101.,invalid=98.,direction='LONG',stage='等待 MSS') for c in codes})
    from datetime import datetime
    from desk.clock import ET
    with patch('desk.store.Store',return_value=store),patch('desk.provider.Provider.fetch',return_value=market_fixture),patch('desk.workspace.now_et',return_value=datetime(2026,10,30,10,10,tzinfo=ET)):
        app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=30).run()
        assert not app.exception
        for c in codes[:4]:assert app.button(key='pick_'+c+'_MANUAL')
        assert len([b for b in app.button if (b.key or '').startswith('pick_')])==4
        assert not any((b.key or '').startswith(('pick_US.VIX','pick_US.DIA')) for b in app.button)
