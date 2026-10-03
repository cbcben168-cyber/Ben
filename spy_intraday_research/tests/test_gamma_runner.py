import json
import pandas as pd
import pytest
from futu import RET_OK,RET_ERROR
from spy_research import gamma_runner as runner

class Quotes:
    def get_option_chain(self,*args,**kwargs):
        return RET_OK,pd.DataFrame({'code':['US.SPY_C','US.SPY_P']})
    def get_market_snapshot(self,codes):
        if codes==['US.SPY']:
            return RET_OK,pd.DataFrame([dict(code='US.SPY',last_price=770,update_time='2026-10-03 10:00:00')])
        return RET_OK,pd.DataFrame([dict(code=code,option_type=kind,option_strike_price=strike,
            option_open_interest=1000,option_implied_volatility=20,option_contract_size=100,
            option_gamma=.01,strike_time='2026-10-09',update_time='2026-10-03 10:00:00')
            for code,kind,strike in [('US.SPY_C','CALL',780),('US.SPY_P','PUT',760)]])

def test_collect_report_hashes_and_tamper_guard(tmp_path,monkeypatch):
    monkeypatch.setattr(runner.time,'sleep',lambda _:None)
    folder=runner.collect(tmp_path,Quotes(),pd.Timestamp('2026-10-03 14:00Z'))
    result=runner.analyze(folder)
    assert not result[1]['formal_data_gate']
    path=runner.report(folder.parent)
    assert '没有实际成交' in path.read_text(encoding='utf-8')
    assert (folder.parent/'gamma_levels.png').exists()
    with (folder/'snapshot.csv').open('a') as stream:stream.write('\n')
    with pytest.raises(ValueError,match='INPUT_HASH'):runner.analyze(folder)

def test_bounded_retries_and_safe_error(monkeypatch):
    monkeypatch.setattr(runner.time,'sleep',lambda _:None)
    calls=[]
    def bad():calls.append(1);return RET_ERROR,'secret-response-do-not-show'
    with pytest.raises(RuntimeError,match='^GAMMA_REQUEST_FAILED$'):runner.request(bad)
    assert len(calls)==3

def test_empty_failure_daily_review(tmp_path):
    day=tmp_path/'2026-10-03';day.mkdir()
    (day/'failure_1.json').write_text(json.dumps(dict(error_type='RuntimeError')))
    path=runner.report(day)
    assert '失败记录：1' in path.read_text(encoding='utf-8')
    choices=pd.read_csv(day/'optimization_choices.csv')
    assert set(choices.status)=={'AWAITING_USER_CHOICE'}
    choices.loc[0,'status']='USER_SELECTED';choices.to_csv(day/'optimization_choices.csv',index=False)
    runner.report(day)
    assert pd.read_csv(day/'optimization_choices.csv').status.iloc[0]=='USER_SELECTED'

def test_existing_watch_lock_never_removed(tmp_path):
    lock=tmp_path/'artifacts/gamma_levels_v1/runner.lock';lock.parent.mkdir(parents=True)
    lock.write_text('other-process')
    assert runner.main(['watch','--once','--root',str(tmp_path)])==1
    assert lock.read_text()=='other-process'
