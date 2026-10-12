from __future__ import annotations

import ast
from pathlib import Path

import pytest

from quant_workflow.factor_research.progress_dashboard.db import canonical_strategy_hash


ROOT = Path(__file__).resolve().parents[4]
STRATEGY_DIR = ROOT / "factor_research" / "spy_factor_batch_v1"
REFERENCE = STRATEGY_DIR / "SPY_SIX_FACTOR_BATCH_TRAIN_V1.py"
FROZEN_V31 = STRATEGY_DIR / "SPY_C1_STRATEGY_BATCH_TRAIN_V3_1.py"
COMPAT_V311 = STRATEGY_DIR / "SPY_C1_STRATEGY_BATCH_TRAIN_V3_1_1.py"
RISKY_PLATFORM_NAMES = {
    "abs",
    "input",
    "max",
    "min",
    "open",
    "round",
    "sorted",
    "sum",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _strategy_class(tree: ast.Module) -> ast.ClassDef:
    return next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "Strategy"
    )


def _methods(path: Path) -> dict[str, ast.FunctionDef]:
    return {
        node.name: node
        for node in _strategy_class(_tree(path)).body
        if isinstance(node, ast.FunctionDef)
    }


def _direct_call_names(node: ast.AST) -> list[str]:
    return [
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
    ]


def _self_call_names(node: ast.AST) -> list[str]:
    return [
        call.func.attr
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "self"
    ]


def _load_strategy(path: Path, framework: dict | None = None):
    namespace = {"StrategyBase": object, **(framework or {})}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace["Strategy"]()


def test_futu_framework_methods_and_initialize_order_match_working_reference():
    required = {"initialize", "trigger_symbols", "custom_indicator", "global_variables"}
    reference_methods = _methods(REFERENCE)
    compat_methods = _methods(COMPAT_V311)
    assert required <= reference_methods.keys()
    assert required <= compat_methods.keys()

    initialize = compat_methods["initialize"]
    ordered_calls = []
    for statement in initialize.body:
        if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
            continue
        function = statement.value.func
        if isinstance(function, ast.Name):
            ordered_calls.append(function.id)
        elif (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id == "self"
        ):
            ordered_calls.append("self." + function.attr)
    assert ordered_calls[:4] == [
        "declare_strategy_type",
        "self.trigger_symbols",
        "self.custom_indicator",
        "self.global_variables",
    ]


def test_declare_trigger_and_setup_are_each_confined_to_the_platform_hook():
    methods = _methods(COMPAT_V311)
    trigger_owners = [
        name for name, node in methods.items() if "declare_trig_symbol" in _direct_call_names(node)
    ]
    setup_owners = [name for name, node in methods.items() if "setup" in _self_call_names(node)]
    assert trigger_owners == ["trigger_symbols"]
    assert setup_owners == ["global_variables"]

    calls = {"trigger": 0, "setup": 0}

    class AlgoStrategyType:
        SECURITY = "SECURITY"

    strategy = _load_strategy(
        COMPAT_V311,
        {
            "AlgoStrategyType": AlgoStrategyType,
            "declare_strategy_type": lambda value: None,
            "declare_trig_symbol": lambda: calls.__setitem__(
                "trigger", calls["trigger"] + 1
            )
            or "US.SPY",
        },
    )
    original_setup = strategy.setup

    def counted_setup():
        calls["setup"] += 1
        original_setup()

    strategy.setup = counted_setup
    strategy.emit = lambda event_type, fields: None
    strategy.initialize()
    assert calls == {"trigger": 1, "setup": 1}
    assert strategy.trig_symbol_1 == "US.SPY"
    assert strategy.strategy_version == "FUTU_C1_STRATEGY_BATCH_TRAIN_V3_1_1"


def test_all_sixteen_native_max_min_calls_are_removed_and_risky_names_are_absent():
    frozen_calls = _direct_call_names(_tree(FROZEN_V31))
    compat_calls = _direct_call_names(_tree(COMPAT_V311))
    assert frozen_calls.count("max") == 10
    assert frozen_calls.count("min") == 6
    assert not (set(compat_calls) & RISKY_PLATFORM_NAMES)


def test_research_constants_and_deterministic_indicator_math_are_frozen():
    frozen_methods = _methods(FROZEN_V31)
    compat_methods = _methods(COMPAT_V311)
    identity_methods = {"initialize", "setup", "emit"}
    for name in frozen_methods.keys() & compat_methods.keys() - identity_methods:
        frozen_numbers = sorted(
            repr(node.value)
            for node in ast.walk(frozen_methods[name])
            if isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        )
        compat_numbers = sorted(
            repr(node.value)
            for node in ast.walk(compat_methods[name])
            if isinstance(node, ast.Constant)
            and isinstance(node.value, (int, float))
            and not isinstance(node.value, bool)
        )
        assert compat_numbers == frozen_numbers, name

    frozen = _load_strategy(FROZEN_V31)
    compat = _load_strategy(COMPAT_V311)
    frozen.setup()
    compat.setup()
    assert compat.definition_hash == frozen.definition_hash
    assert compat.system_start == frozen.system_start
    assert compat.study_start == frozen.study_start
    assert compat.study_end == frozen.study_end
    assert compat.early_close_days == frozen.early_close_days
    assert compat.rehab_adjustments == frozen.rehab_adjustments

    for index in range(40):
        close = 100.0 + index * 0.11 + (-0.08 if index % 3 == 0 else 0.05)
        source = {
            "open": close - 0.04,
            "high": close + 0.17,
            "low": close - 0.13,
            "close": close,
        }
        frozen_bar = dict(source)
        compat_bar = dict(source)
        frozen.update_indicators(frozen_bar)
        compat.update_indicators(compat_bar)
        assert compat_bar["tr"] == pytest.approx(frozen_bar["tr"])
        assert compat.ema20 == pytest.approx(frozen.ema20)
        assert compat.ema50 == pytest.approx(frozen.ema50)
        assert compat.atr(14) == pytest.approx(frozen.atr(14))
    assert compat.median([3.0, 1.0, 4.0, 2.0]) == frozen.median([3.0, 1.0, 4.0, 2.0])


def test_v311_identity_hash_and_safety_boundary_are_self_consistent():
    source = COMPAT_V311.read_text(encoding="utf-8")
    assert canonical_strategy_hash(COMPAT_V311) in source
    assert '"contract_version": "3.1.1"' in source
    assert "FUTU_FACTOR_STRATEGY_V3_1_1|" in source
    assert '"parameter_attempt": 3' in source
    for forbidden in (
        "place_order",
        "get_position",
        "account_",
        "bar_volume",
        "vwap",
    ):
        assert forbidden not in source.lower()
