from datetime import datetime

import pandas as pd

from desk.clock import ET
from desk.decision_home import historical_plan, manual_prices
from desk.market_state import market_state


def test_replay_excludes_later_daily_bar_and_close_quarantine():
    rows = pd.DataFrame(dict(ts=pd.DatetimeIndex(['2026-10-29', '2026-11-02'], tz=ET),
                             close=[100.0, 900.0], eligible=True))
    state, chart = market_state(rows, '1D', datetime(2026,10,29,16,2,tzinfo=ET), 'ARCHIVE')
    assert list(chart.close) == [100.0]
    assert state['trend'] == 'UNKNOWN'
    assert state['at'].hour == 16
    state, chart = market_state(rows, '1D', datetime(2026,10,29,16,1,tzinfo=ET), 'ARCHIVE')
    assert chart.empty and state['at'] is None


def test_linked_structure_and_no_fabricated_targets():
    sweep = dict(id='sweep', confirmed_at='2026-10-29T12:32:00-04:00', source='fixture')
    fvg = dict(id='fvg', confirmed_at='2026-10-29T14:32:00-04:00', source='fixture')
    structure = dict(linked=True, stage='FVG_CONFIRMED', region=(100, 101), invalid=95,
                     direction='LONG', until='2026-10-30T10:32:00-04:00',
                     event_id=fvg['id'], confirmed_at=fvg['confirmed_at'], evidence=[sweep, fvg])
    result = historical_plan(dict(qualification=1, structure=structure))
    assert (result['low'], result['high'], result['invalid']) == (100, 101, 95)
    assert result['invalid_confirmed_at'] == sweep['confirmed_at']
    assert not {'target1', 'target2', 'rr1', 'rr2'} & result.keys()
    assert historical_plan(dict(qualification=1, structure=dict(structure, stage='INVALIDATED'))) is None
    assert historical_plan(dict(qualification=1, structure=dict(structure, linked=False))) is None
    assert historical_plan(dict(qualification=2, structure=structure)) is None


def test_short_rr_uses_lower_entry_and_nearest_target_first():
    plan = dict(symbol='US.SPY', strategy_version='test', status='ACTIVE', direction='SHORT',
                low=100, high=101, invalid=105, target_low=85, target_high=90)
    result = manual_prices(plan)
    assert (result['entry'], result['risk'], result['target1'], result['target2']) == (100, 5, 90, 85)
    assert (result['rr1'], result['rr2']) == (2, 3)
    assert manual_prices(dict(plan, invalid=100)) is None
    assert manual_prices(dict(plan, target_high=None)) is None
