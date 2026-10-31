from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
from scripts.live_rth_acceptance import plan, read_user_state, main


def test_dst_plan_and_no_network_by_default(capsys):
    p=plan()
    assert p['星期一开盘']=='2026-11-02T09:30:00-05:00'
    assert p['香港时间']=='2026-11-02T22:30:00+08:00'
    with patch('sys.argv',['live_rth_acceptance.py']),patch('desk.provider.Provider',side_effect=AssertionError('default must not connect')):
        main()
    assert 'PENDING_LIVE_ACCEPTANCE' in capsys.readouterr().out


def test_weekend_capture_does_not_connect(capsys):
    with patch('sys.argv',['live_rth_acceptance.py','--capture']),patch('scripts.live_rth_acceptance.now_et',return_value=datetime(2026,10,31,12,tzinfo=ZoneInfo('America/New_York'))),patch('desk.provider.Provider',side_effect=AssertionError('weekend must not connect')):
        main()
    assert 'PENDING_LIVE_ACCEPTANCE' in capsys.readouterr().out


def test_user_state_read_is_stable(tmp_path,monkeypatch):
    from desk.store import Store
    Store(tmp_path/'data/desk.sqlite3')
    monkeypatch.setattr('scripts.live_rth_acceptance.ROOT',tmp_path)
    before=read_user_state()
    assert before==read_user_state()
