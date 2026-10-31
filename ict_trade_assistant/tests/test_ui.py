from pathlib import Path
from unittest.mock import patch
import pandas as pd
from streamlit.testing.v1 import AppTest
from desk.store import Store

ROOT = Path(__file__).resolve().parents[1]


def test_navigation_settings_notes(tmp_path):
    store = Store(tmp_path/'ui.sqlite3')
    fixture = dict(health=dict(quality='UNAVAILABLE', reason='test disconnected', right='UNKNOWN',
                               source='TEST_OFFLINE', received_at='2026-10-29T00:00:00Z'),
                   minute=pd.DataFrame(), daily=pd.DataFrame(), errors=[])
    with patch('desk.store.Store', return_value=store), patch('desk.provider.Provider.fetch', return_value=fixture):
        app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=30).run()
        assert not app.exception
        app.sidebar.radio[0].set_value('设置与审计').run()
        assert not app.exception
        app.number_input[0].set_value(25.)
        app.button[0].click().run()
        assert store.settings()['distance_bps'] == 25.
        app.sidebar.radio[0].set_value('事件与备注').run()
        app.text_area[0].set_value('offline UI test note')
        app.button[0].click().run()
        assert 'offline UI test note' in store.table('events').reason.tolist()
        for page in ['SOP 与进度', '其他策略', '交易记录', '期权']:
            app.sidebar.radio[0].set_value(page).run()
            assert not app.exception
