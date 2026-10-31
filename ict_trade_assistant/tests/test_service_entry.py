import logging
import pytest
from scripts.run_server import run_entry


def test_normal_system_exit_is_not_error(caplog):
    log=logging.getLogger('ict.entry.test')
    with caplog.at_level(logging.INFO):
        assert run_entry(lambda: (_ for _ in ()).throw(SystemExit(0)), log)==0
    assert not any(r.levelno>=logging.ERROR for r in caplog.records)


def test_abnormal_exit_still_propagates(caplog):
    with pytest.raises(RuntimeError):
        run_entry(lambda: (_ for _ in ()).throw(RuntimeError('injected entry failure')),logging.getLogger('ict.entry.test'))
    assert any(r.levelno==logging.ERROR for r in caplog.records)


def test_nonzero_system_exit_is_error(caplog):
    with pytest.raises(SystemExit) as caught:
        run_entry(lambda: (_ for _ in ()).throw(SystemExit(2)),logging.getLogger('ict.entry.test'))
    assert caught.value.code==2
    assert any(r.levelno==logging.ERROR for r in caplog.records)
