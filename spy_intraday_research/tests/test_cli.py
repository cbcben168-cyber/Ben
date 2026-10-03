import json
from types import SimpleNamespace
import pandas as pd
import pytest
from spy_research import cli
import spy_research.futu_quotes as quotes

def test_checkpoint_idempotence_and_tamper(tmp_path, monkeypatch):
    calls=[]
    class Reader:
        def __init__(self,*args): pass
        def history(self,start,end,kind):
            calls.append(kind)
            return pd.DataFrame({'code':['US.SPY'],'time_key':[start+' 09:31:00']})
        def close(self): pass
    monkeypatch.setattr(cli,'ROOT',tmp_path)
    monkeypatch.setattr(quotes,'QuoteReader',Reader)
    args=SimpleNamespace(start='2026-10-02',end='2026-10-02')
    config={'request_interval_seconds':0,'max_retries':1}
    cli.ingest(args,config)
    cli.ingest(args,config)
    assert len(calls)==3
    raw=tmp_path/'data/raw/K_1M/2026-10-02.csv'
    raw.write_text('tampered')
    with pytest.raises(ValueError,match='HASH_MISMATCH'): cli.ingest(args,config)

def test_atomic_write(tmp_path):
    target=tmp_path/'new/output.json'
    cli.atomic(target,json.dumps({'status':'SUCCESS'}))
    assert json.loads(target.read_text())['status']=='SUCCESS'
    assert not target.with_suffix('.json.tmp').exists()
