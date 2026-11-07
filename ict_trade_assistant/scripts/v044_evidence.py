"""Deterministic acceptance using existing copied real historical archives only."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import pandas as pd
from desk.clock import ET
from desk.experiment import BASELINE, ExperimentStore, completed_snapshot, distance_result, replay_cutoff
from desk.history_import import DailyArchive
from desk.history_source import HistorySource
from desk.market_state import market_state
from desk.decision_home import _replay_decision


def run():
    source = HistorySource(ROOT/'data/v04/history.json', datetime(2026,10,29,16,2,tzinfo=ET),
                           DailyArchive(ROOT/'data/v042/history.sqlite3'), DailyArchive(ROOT/'data/v043/updates.sqlite3'))
    wall = datetime(2026,11,7,tzinfo=ET)
    codes = ('US.SPY','US.QQQ','US.IWM','US.SOXX','US.SMH')
    original = {'__package__': 'desk'}
    baseline_source = subprocess.check_output(['git','show','da7624a:ict_trade_assistant/desk/market_state.py'], cwd=ROOT, text=True, encoding='utf-8')
    exec(compile(baseline_source, 'PR46-market_state.py', 'exec'), original)
    evidence = dict(version='v0.4.4', baseline='da7624a', defaults=asdict(BASELINE), symbols=[], factors=[], replay=[])
    for code in codes:
        data = source.fetch(code)
        state, frame = market_state(data['daily'], '1D', wall, data['health']['source'])
        old, _ = original['market_state'](data['daily'], '1D', wall, data['health']['source'])
        assert all(state[k] == v for k, v in old.items()), (code, 'baseline differs')
        assert market_state(data['daily'], '1D', wall, state['source'])[0] == state
        candidate = distance_result(data, state, BASELINE, '1D')
        evidence['symbols'].append(dict(symbol=code, state=state, distance=candidate, minute_rows=len(data['minute']),
                                        baseline_parity=True, deterministic=True))
        day = datetime(2026,10,28).date()
        cutoff = replay_cutoff(day)
        replay, prefix = market_state(data['daily'], '1D', cutoff, state['source'])
        poisoned = data['daily'].copy()
        future = poisoned.ts.dt.date > day
        poisoned.loc[future, ['open','high','low','close']] *= 1000
        check, _ = market_state(poisoned, '1D', cutoff, state['source'])
        assert replay == check
        assert prefix.closed_at.max() + timedelta(minutes=2) <= cutoff
        snapshot = completed_snapshot(data, cutoff)
        if not snapshot['minute'].empty:
            assert (snapshot['minute'].ts + timedelta(minutes=3) <= cutoff).all()
        decision = _replay_decision(code, data, cutoff)
        assert decision['ict_live_qualification']['qualified'] is False
        assert all(pd.Timestamp(e['confirmed_at']) <= cutoff for e in decision['evidence'])
        evidence['replay'].append(dict(symbol=code, cutoff=cutoff, rows=len(prefix), last_close=prefix.closed_at.max(),
                                       excluded_future=int(future.sum()), poison_future_invariant=True,
                                       minute_rows=len(snapshot['minute']), ict_live_qualified=False))
        if code == 'US.SMH':
            assert candidate['eligible'] is None and not decision['live_review']
    for key, value, code, field in (
        ('ema_short',5,'US.SPY','ema20'), ('ema_long',35,'US.SPY','ema50'),
        ('atr_period',7,'US.SPY','atr14'), ('sideways_atr',.10,'US.SPY','sideways_margin'),
        ('candidate_atr',.05,'US.QQQ','eligible')):
        data = source.fetch(code)
        config = replace(BASELINE, **{key:value})
        baseline, _ = market_state(data['daily'],'1D',wall,data['health']['source'])
        changed, _ = market_state(data['daily'],'1D',wall,baseline['source'],config)
        before = distance_result(data,baseline,BASELINE,'1D')
        after = distance_result(data,changed,config,'1D')
        a, b = (before[field],after[field]) if key == 'candidate_atr' else (baseline[field],changed[field])
        assert a != b, (key, 'input did not affect output')
        assert market_state(data['daily'],'1D',wall,baseline['source'],BASELINE)[0] == baseline
        evidence['factors'].append(dict(parameter=key, default=asdict(BASELINE)[key], input=value, symbol=code,
                                        output=field, before=a, after=b, restored=True,
                                        original_trend=baseline['trend'], experiment_trend=changed['trend'],
                                        original_volatility=baseline['volatility'], experiment_volatility=changed['volatility']))
    store = ExperimentStore(ROOT/'data/v044/evidence-experiments.sqlite3')
    config = replace(BASELINE, ema_short=5)
    store.save('验收_短期5',config)
    assert ExperimentStore(store.path).load('验收_短期5') == config
    try:
        store.save('Baseline',config)
        raise AssertionError('Baseline overwritten')
    except ValueError:
        pass
    evidence['storage'] = dict(reopened=True, baseline_overwrite_rejected=True, defaults_restored=store.load('Baseline')==BASELINE)
    target = ROOT/'data/v044/real-evidence.json'
    target.write_text(json.dumps(evidence,ensure_ascii=False,indent=2,default=str,allow_nan=False),encoding='utf-8')
    print(json.dumps(dict(symbols=len(codes), factors=len(evidence['factors']), replay_cases=len(evidence['replay']),
                          all_assertions_passed=True, report=str(target)), ensure_ascii=False))


if __name__ == '__main__':
    run()
