import ast
import hashlib
import json
from pathlib import Path
import re
import runpy
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
STRATEGY_PATH = ROOT / "SPY_FACTOR_RESEARCH_TRAIN_V1.py"


def load_strategy():
    env = {
        "StrategyBase": object,
        "declare_strategy_type": lambda _: None,
        "declare_trig_symbol": lambda: "TRIGGER_SPY",
        "AlgoStrategyType": SimpleNamespace(SECURITY="SECURITY"),
        "BarType": SimpleNamespace(K_5M="K_5M"),
        "THType": SimpleNamespace(RTH="RTH"),
        "DataType": SimpleNamespace(CLOSE="CLOSE"),
        "TimeZone": SimpleNamespace(ET="ET", UTC="UTC"),
        "device_time": lambda _: None,
        "get_symbol_code": lambda **_: "US.SPY",
        "bar_close": lambda **_: 100.0,
        "ema": lambda **_: 99.0,
    }
    strategy_class = runpy.run_path(str(STRATEGY_PATH), init_globals=env)["Strategy"]
    strategy = strategy_class()
    strategy.initialize()
    return strategy


def test_train_strategy_preserves_frozen_factor_and_disables_execution_apis():
    source = STRATEGY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert isinstance(tree.body[0], ast.ClassDef)
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree))
    assert ast.get_docstring(tree) is None

    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    forbidden = {
        "bar_volume", "place_order", "unlock_trade", "modify_order",
        "OpenSecTradeContext", "OpenFutureTradeContext", "get_acc_list",
        "position_list_query", "accinfo_query", "subscribe", "requests", "urlopen",
    }
    assert not (names | attributes) & forbidden

    market_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"bar_close", "ema"}
    ]
    assert market_calls
    assert all(
        isinstance({item.arg: item.value for item in call.keywords}["select"], ast.Constant)
        and {item.arg: item.value for item in call.keywords}["select"].value == 2
        for call in market_calls
    )
    assert '"horizons_bars": "3,6,12"' in source
    assert '"volume_enabled": False' in source
    assert '"orders_enabled": False' in source


def test_train_strategy_hash_and_run_start_contract(capsys):
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

    strategy = load_strategy()
    line = next(
        item for item in capsys.readouterr().out.splitlines()
        if item.startswith("FUTU_FACTOR_V1|")
    )
    start = json.loads(line.split("|", 1)[1])
    assert start["study_partition"] == "TRAIN"
    assert start["study_start_et"] == "2025-10-01"
    assert start["study_end_et"] == "2026-06-30"
    assert start["formula"] == "close(select=2)>ema20(select=2)"
    assert start["horizons_bars"] == "3,6,12"
    assert start["volume_enabled"] is False
    assert start["orders_enabled"] is False
    assert strategy.run_id == "SPY_F001_TRAIN_20251001_20260630_V1"
    assert strategy.expected_session_count == 187


def test_train_session_counts_include_two_frozen_early_closes(capsys):
    strategy = load_strategy()
    capsys.readouterr()
    assert strategy.expected_events_for_day(20251001) == 65
    assert strategy.expected_events_for_day(20251128) == 29
    assert strategy.expected_events_for_day(20251224) == 29
    assert set(strategy.early_close_days) == {20251128, 20251224}
    assert strategy.study_start == 20251001
    assert strategy.study_end == 20260630
