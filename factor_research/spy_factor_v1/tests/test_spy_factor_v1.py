import ast
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = ROOT / "SPY_FACTOR_RESEARCH_V1.py"
ET = timezone(timedelta(hours=-4))


def parse_line(line):
    prefix, payload = line.strip().split("|", 1)
    assert prefix == "FUTU_FACTOR_V1"
    result = json.loads(payload)
    return {
        key: ("TRUE" if value is True else "FALSE" if value is False else str(value))
        for key, value in result.items()
    }


def platform(close_by_minute=None, ema_by_minute=None, symbol="US.SPY"):
    state = {"clock": datetime(2026, 9, 28, 9, 35, tzinfo=ET)}
    calls = []
    close_by_minute = close_by_minute or {}
    ema_by_minute = ema_by_minute or {}

    def minute():
        return state["clock"].hour * 60 + state["clock"].minute

    def device_time(zone):
        if zone == "UTC":
            return state["clock"].astimezone(timezone.utc).replace(tzinfo=None)
        return state["clock"].replace(tzinfo=None)

    def bar_close(**kwargs):
        calls.append(("bar_close", minute(), kwargs))
        value = close_by_minute.get(minute(), 100.0 + minute() / 1000.0)
        if isinstance(value, Exception):
            raise value
        return value

    def ema(**kwargs):
        calls.append(("ema", minute(), kwargs))
        value = ema_by_minute.get(minute(), 100.0)
        if isinstance(value, Exception):
            raise value
        return value

    env = {
        "StrategyBase": object,
        "declare_strategy_type": lambda _: None,
        "declare_trig_symbol": lambda: "TRIGGER_SPY",
        "AlgoStrategyType": SimpleNamespace(SECURITY="SECURITY"),
        "BarType": SimpleNamespace(K_5M="K_5M"),
        "THType": SimpleNamespace(RTH="RTH"),
        "DataType": SimpleNamespace(CLOSE="CLOSE"),
        "TimeZone": SimpleNamespace(ET="ET", UTC="UTC"),
        "device_time": device_time,
        "get_symbol_code": lambda **_: symbol,
        "bar_close": bar_close,
        "ema": ema,
    }
    strategy_class = runpy.run_path(str(STRATEGY_PATH), init_globals=env)["Strategy"]
    strategy = strategy_class()
    strategy.initialize()
    return strategy, state, calls


def run_at(strategy, state, day, hour, minute):
    state["clock"] = datetime(day.year, day.month, day.day, hour, minute, tzinfo=ET)
    strategy.handle_data()


def records(capsys):
    return [
        parse_line(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("FUTU_FACTOR_V1|")
    ]


def test_strategy_file_has_required_futu_shape_and_no_forbidden_api():
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert isinstance(tree.body[0], ast.ClassDef)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    assert ast.get_docstring(tree) is None

    methods = {node.name: node for node in tree.body[0].body if isinstance(node, ast.FunctionDef)}
    assert {"initialize", "trigger_symbols", "custom_indicator", "global_variables", "handle_data"} <= methods.keys()
    trigger_calls = [node for node in ast.walk(methods["trigger_symbols"]) if isinstance(node, ast.Call)]
    assert any(isinstance(call.func, ast.Name) and call.func.id == "declare_trig_symbol" for call in trigger_calls)

    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    forbidden = {
        "bar_volume", "place_order", "unlock_trade", "modify_order",
        "OpenSecTradeContext", "OpenFutureTradeContext", "get_acc_list",
        "position_list_query", "accinfo_query", "subscribe", "requests", "urlopen"
    }
    assert not (names | attributes) & forbidden

    market_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"bar_close", "ema"}
    ]
    assert market_calls
    for call in market_calls:
        keywords = {item.arg: item.value for item in call.keywords}
        assert isinstance(keywords["select"], ast.Constant)
        assert keywords["select"].value == 2


def test_strategy_emits_versioned_factor_contract_and_canonical_hash(capsys):
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    match = re.search(r'self\.strategy_hash = "([0-9a-f]{64})"', source)
    assert match
    normalized = re.sub(
        r'(self\.strategy_hash = ")[0-9a-f]{64}(".*)',
        r'\g<1>' + ("0" * 64) + r'\g<2>',
        source,
        count=1,
    )
    assert match.group(1) == hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    platform()
    start = records(capsys)[0]
    assert start["event_type"] == "RUN_START"
    assert start["contract_version"] == "1.0"
    assert start["factor_id"] == "SPY_F001_CLOSE_GT_EMA20"
    assert start["strategy_hash"] == match.group(1)
    assert start["orders_enabled"] == "FALSE"


def test_0930_is_not_read_and_h3_waits_for_due_completed_bar(capsys):
    strategy, state, calls = platform(
        close_by_minute={575: 100.0, 580: 101.0, 585: 102.0, 590: 103.0},
        ema_by_minute={575: 99.0}
    )
    day = datetime(2026, 9, 28)
    records(capsys)
    run_at(strategy, state, day, 9, 30)
    assert calls == []
    for value in (35, 40, 45):
        run_at(strategy, state, day, 9, value)
    before_due = records(capsys)
    assert len([item for item in before_due if item["record"] == "EVENT"]) == 3
    assert not [item for item in before_due if item["record"] == "OUTCOME"]

    run_at(strategy, state, day, 9, 50)
    due = records(capsys)
    outcomes = [item for item in due if item["record"] == "OUTCOME"]
    assert len(outcomes) == 1
    assert outcomes[0]["event_id"] == "20260928_0935"
    assert outcomes[0]["horizon_bars"] == "3"
    assert outcomes[0]["factor_state"] == "PASS"
    assert float(outcomes[0]["return"]) == pytest.approx(0.03)
    assert outcomes[0]["signal_et"].startswith("2026-09-28T09:35")
    assert outcomes[0]["outcome_et"].startswith("2026-09-28T09:50")


def test_full_day_has_65_events_and_partitioned_summaries(capsys):
    close_map = {minute: 100.0 + (minute - 575) * 0.01 for minute in range(575, 956, 5)}
    ema_map = {
        minute: close_map[minute] - 1.0 if ((minute - 575) // 5) % 2 == 0 else close_map[minute] + 1.0
        for minute in range(575, 896, 5)
    }
    strategy, state, _ = platform(close_map, ema_map)
    records(capsys)
    day = datetime(2026, 9, 28)
    for minute in range(575, 956, 5):
        run_at(strategy, state, day, minute // 60, minute % 60)
    result = records(capsys)

    assert len([item for item in result if item["record"] == "EVENT"]) == 65
    for horizon in ("3", "6", "12"):
        assert len([
            item for item in result
            if item["record"] == "OUTCOME" and item["horizon_bars"] == horizon
        ]) == 65

    day_status = [item for item in result if item["record"] == "DAY_STATUS"][-1]
    assert day_status["status"] == "COMPLETE"
    assert day_status["event_count"] == "65"
    assert day_status["error_count"] == "0"

    summaries = [item for item in result if item["record"] == "SUMMARY" and item["scope"] == "DAY"]
    assert len(summaries) == 9
    for horizon in ("3", "6", "12"):
        grouped = {item["group"]: item for item in summaries if item["horizon_bars"] == horizon}
        assert int(grouped["PASS"]["n"]) + int(grouped["FAIL"]["n"]) == int(grouped["ALL"]["n"]) == 65
        assert grouped["ALL"]["delta_mean_vs_all"] == "0.0000000000"
        assert grouped["PASS"]["independent_samples"] == "FALSE"


def test_previous_day_pending_is_rejected_instead_of_crossing_overnight(capsys):
    strategy, state, _ = platform()
    records(capsys)
    run_at(strategy, state, datetime(2026, 9, 28), 14, 55)
    records(capsys)
    run_at(strategy, state, datetime(2026, 9, 29), 9, 35)
    result = records(capsys)
    errors = [item for item in result if item["record"] == "ERROR"]
    assert any(item["code"] == "UNRESOLVED_PREVIOUS_DAY" and item["detail"] == "3" for item in errors)
    assert not [item for item in result if item["record"] == "OUTCOME"]


def test_invalid_ema_and_symbol_fail_visible_without_fabricated_event(capsys):
    strategy, state, _ = platform(ema_by_minute={575: RuntimeError("PRIVATE_VALUE")})
    records(capsys)
    run_at(strategy, state, datetime(2026, 9, 28), 9, 35)
    result = records(capsys)
    assert not [item for item in result if item["record"] == "EVENT"]
    assert any(item["code"] == "EMA20_READ_FAILED" and item["detail"] == "RuntimeError" for item in result)
    assert "PRIVATE_VALUE" not in str(result)

    strategy, state, _ = platform(symbol="US.QQQ")
    records(capsys)
    run_at(strategy, state, datetime(2026, 9, 28), 9, 35)
    result = records(capsys)
    assert any(item["code"] == "SYMBOL_CHECK_FAILED" for item in result)
    assert not [item for item in result if item["record"] == "EVENT"]


def test_outside_fixed_validation_dates_is_ignored(capsys):
    strategy, state, calls = platform()
    records(capsys)
    run_at(strategy, state, datetime(2026, 9, 25), 9, 35)
    run_at(strategy, state, datetime(2026, 10, 7), 9, 35)
    assert calls == []
    assert records(capsys) == []


def test_seven_day_validation_window_reaches_455_cumulative_outcomes(capsys):
    strategy, state, _ = platform()
    records(capsys)
    trading_days = [
        datetime(2026, 9, 28), datetime(2026, 9, 29), datetime(2026, 9, 30),
        datetime(2026, 10, 1), datetime(2026, 10, 2),
        datetime(2026, 10, 5), datetime(2026, 10, 6)
    ]
    for day in trading_days:
        for minute in range(575, 956, 5):
            run_at(strategy, state, day, minute // 60, minute % 60)
    result = records(capsys)

    statuses = [item for item in result if item["record"] == "DAY_STATUS"]
    assert len(statuses) == 7
    assert all(item["status"] == "COMPLETE" for item in statuses)
    final = [
        item for item in result
        if item["record"] == "SUMMARY"
        and item["scope"] == "CUMULATIVE"
        and item["group"] == "ALL"
        and item["session_date_et"] == "2026-10-06"
    ]
    assert {item["horizon_bars"]: int(item["n"]) for item in final} == {
        "3": 455, "6": 455, "12": 455
    }
    run_end = [item for item in result if item["event_type"] == "RUN_END"]
    assert len(run_end) == 1
    assert run_end[0]["status"] == "COMPLETE"
    assert run_end[0]["signal_count"] == "455"
