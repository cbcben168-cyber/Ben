import json
from pathlib import Path
import pandas as pd
import pytest
from spy_research import research,shadow
from spy_research.storage import write_json,digest
from spy_research.workflow import main

def test_no_candidate_cannot_consume_validation(tmp_path,monkeypatch):
    minute=pd.DataFrame();bars=pd.DataFrame();events=pd.DataFrame()
    monkeypatch.setattr(research,'context',lambda root:(minute,bars,events,{}, {}, {}))
    with pytest.raises(ValueError,match='NO_VALIDATED_CANDIDATES'):
        research.evaluate(tmp_path,'validation',[])
    assert not (tmp_path/'artifacts/research/baseline_v1/validation').exists()

def test_lock_refuses_unqualified_validation(tmp_path):
    write_json(tmp_path/'artifacts/research/baseline_v1/validation/result.json',dict(candidates=[{'setup':'ORB15','direction':1}],formal_data_gate=False))
    with pytest.raises(ValueError,match='NO_VALIDATED_CANDIDATES'): research.lock(tmp_path)

def test_diagnostic_lock_is_immutable(tmp_path):
    write_json(tmp_path/'locks/baseline_v1/state_model.json',{})
    write_json(tmp_path/'data/normalized/manifest.json',{})
    path=shadow.freeze_diagnostic(tmp_path,'diagnostic_v2')
    first=digest(path)
    assert shadow.freeze_diagnostic(tmp_path,'diagnostic_v2')==path and digest(path)==first
    payload=json.loads(path.read_text());payload['runtime_sha256']='tampered';write_json(path,payload)
    with pytest.raises(ValueError,match='SOURCE_CHANGED'): shadow.freeze_diagnostic(tmp_path,'diagnostic_v2')

def test_real_or_broker_mode_has_no_cli_path():
    with pytest.raises(SystemExit): main(['paper','--mode','broker-paper'])

def test_bounded_workflow_sanitizes_errors(tmp_path):
    assert main(['paper','--once','--root',str(tmp_path)])==1
    manifests=list((tmp_path/'logs/workflow').glob('*/manifest.json'))
    assert json.loads(manifests[0].read_text())['error']=='FileNotFoundError: CHECK_WORKFLOW_INPUTS'

def test_science_source_guard_on_live_runner(tmp_path):
    path=tmp_path/'lock.json'
    write_json(path,dict(mode='diagnostic-shadow',orders_enabled=False,source_sha256='wrong',runtime_sha256='wrong'))
    with pytest.raises(ValueError,match='LOCK_INVALID'): shadow.run(tmp_path,path,once=True)
