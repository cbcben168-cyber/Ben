import ast
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("workflow_probe", ROOT / "opend_data_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def bars(day="2026-10-06", minutes=1, label="end"):
    stamps = probe.expected_grid(day, minutes)
    if label == "end":
        stamps = stamps + pd.Timedelta(minutes=minutes)
    return pd.DataFrame({"code": "US.SPY", "time_key": stamps.tz_convert("America/New_York").strftime("%Y-%m-%d %H:%M:%S"),
                         "open": 100., "high": 102., "low": 99., "close": 101., "volume": 10 * minutes})


@pytest.mark.parametrize("day,count", [("2026-10-06", 390), ("2025-11-28", 210)])
@pytest.mark.parametrize("label", ["start", "end"])
def test_calendar_and_labels(day, count, label):
    one, five = bars(day, label=label), bars(day, 5, label=label)
    result = probe.audit_frames(one, five, day, "US.SPY")
    assert result["status"] == "SAMPLE_CHECKS_PASS"
    assert result["1m"]["rows"] == count
    assert result["1m"]["label_semantics"] == label
    assert result["strategy_qualification"] == "NOT_VERIFIED"


def test_dst_and_nontrading_day():
    assert probe.expected_grid("2026-03-06", 1)[0].hour == 14
    assert probe.expected_grid("2026-03-09", 1)[0].hour == 13
    with pytest.raises(ValueError):
        probe.expected_grid("2026-10-04", 1)


@pytest.mark.parametrize("change,expected", [
    (lambda f: f.drop(index=15), "COVERAGE_OR_LABELS_UNRESOLVED"),
    (lambda f: pd.concat([f, f.iloc[[0]]]), "DUPLICATE_TIMESTAMP"),
    (lambda f: f.iloc[::-1], "UNSORTED_TIMESTAMP"),
    (lambda f: f.assign(close=float("nan")), "NONFINITE_OHLCV"),
    (lambda f: f.assign(high=float("inf")), "NONFINITE_OHLCV"),
    (lambda f: f.assign(low=103), "INVALID_OHLC"),
    (lambda f: f.assign(volume=-1), "NEGATIVE_VOLUME"),
    (lambda f: f.assign(volume=True), "BOOLEAN_VALUE"),
    (lambda f: f.assign(code="US.QQQ"), "SYMBOL_MISMATCH"),
    (lambda f: f.assign(time_key=None), "INVALID_TIMESTAMP"),
])
def test_fail_closed(change, expected):
    result = probe.audit_frames(change(bars()), bars(minutes=5), "2026-10-06", "US.SPY")
    assert result["status"] == "FAILED_DATA"
    assert expected in result["1m"]["errors"]
    assert result["cross_period"] == "NOT_VERIFIED"


def test_volume_mismatch_does_not_hide_price_match():
    five = bars(minutes=5)
    five.loc[0, "volume"] = 51
    result = probe.audit_frames(bars(), five, "2026-10-06", "US.SPY")
    assert result["status"] == "FAILED_DATA"
    assert result["cross_period"]["price_mismatch_bars"] == 0
    assert result["cross_period"]["volume_mismatch_bars"] == 1


def test_price_mismatch_and_zero_volume():
    five = bars(minutes=5)
    five.loc[0, "high"] = 103
    result = probe.audit_frames(bars(), five, "2026-10-06", "US.SPY")
    assert result["cross_period"]["price_mismatch_bars"] == 1
    result = probe.audit_frames(bars().assign(volume=0), bars(minutes=5).assign(volume=0), "2026-10-06", "US.SPY")
    assert result["status"] == "NOT_VERIFIED"


def test_repeated_pagination_and_server_errors_are_sanitized(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "futu", SimpleNamespace(AuType=SimpleNamespace(NONE="NONE"), RET_OK=0,
                                                           Session=SimpleNamespace(RTH="RTH")))
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return 0, bars(), b"same"
    with pytest.raises(RuntimeError, match="PAGINATION_NO_PROGRESS"):
        probe.fetch_history(SimpleNamespace(request_history_kline=request), "US.SPY", "2026-10-06", "1m")
    assert len(calls) == 2
    assert all(c["session"] == "RTH" and c["autype"] == "NONE" for c in calls)
    with pytest.raises(RuntimeError, match="^HISTORY_REQUEST_REJECTED$"):
        probe.fetch_history(SimpleNamespace(request_history_kline=lambda *a, **k: (1, "private server message", None)), "US.SPY", "2026-10-06", "1m")


def platform(overrides=None):
    calls = []
    def reader(value):
        def read(**kwargs):
            calls.append(kwargs)
            return value
        return read
    env = {"StrategyBase": object, "declare_strategy_type": lambda _: None,
           "declare_trig_symbol": lambda: "US.SPY", "AlgoStrategyType": SimpleNamespace(SECURITY="SECURITY"),
           "BarType": SimpleNamespace(K_1M="1m", K_5M="5m"), "THType": SimpleNamespace(RTH="RTH"),
           "DataType": SimpleNamespace(CLOSE="CLOSE"), "TimeZone": SimpleNamespace(UTC="UTC"),
           "device_time": lambda _: datetime(2026, 10, 6, 13, 35, tzinfo=timezone.utc),
           "get_symbol_code": lambda **_: "US.SPY",
           "bar_open": reader(100), "bar_high": reader(102), "bar_low": reader(99),
           "bar_close": reader(101), "bar_volume": reader(10), "ema": reader(100)}
    env.update(overrides or {})
    cls = runpy.run_path(str(ROOT / "platform_data_probe.py"), init_globals=env)["Strategy"]
    strategy = cls()
    strategy.initialize()
    return strategy, calls


def last_record(capsys):
    return json.loads(capsys.readouterr().out.splitlines()[-1].removeprefix("FUTU_DATA_PROBE "))


def test_platform_logs_values_without_claiming_bar_completion(capsys):
    strategy, calls = platform()
    strategy.handle_data()
    result = last_record(capsys)
    assert result["error_count"] == 0
    assert result["qualification"] == result["5m"]["bar_completion"] == "NOT_VERIFIED"
    assert result["5m"]["source_bar_timestamp"] is None
    assert result["trigger_time_utc"].endswith("+00:00")
    assert all(c["select"] == 2 and c["session_type"] == "RTH" for c in calls)
    strategy.handle_data()
    assert "NONINCREASING_TRIGGER" in last_record(capsys)["issues"]


def test_platform_missing_data_and_clock_are_not_filled(capsys):
    strategy, _ = platform({"bar_close": lambda **_: float("nan"),
                            "device_time": lambda _: datetime(2026, 10, 6)})
    strategy.handle_data()
    result = last_record(capsys)
    assert result["5m"]["close"] is None
    assert result["trigger_time_utc"] is None
    assert result["error_count"] == 1


def test_platform_api_exception_does_not_leak_message(capsys):
    def failure(**_):
        raise RuntimeError("SENSITIVE_TEST_VALUE")
    strategy, _ = platform({"ema": failure})
    strategy.handle_data()
    output = capsys.readouterr().out
    assert "SENSITIVE_TEST_VALUE" not in output
    assert "ema20:RuntimeError" in output


def test_probes_have_no_order_account_subscription_or_network_client_calls():
    forbidden = {"place_order", "unlock_trade", "modify_order", "OpenSecTradeContext", "OpenFutureTradeContext",
                 "get_acc_list", "position_list_query", "accinfo_query", "subscribe", "urlopen", "requests"}
    for name in ("platform_data_probe.py", "opend_data_probe.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        identifiers = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        identifiers |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not identifiers & forbidden
