"""Tests for the formal, immutable V2.1 execution-assumptions boundary."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from types import MappingProxyType

import pytest

from tv_quant.contracts.data_plan import build_data_plan
from tv_quant.contracts.normalized_ir import normalize_strategy_spec
from tv_quant.contracts.strategy_v2 import validate_strategy_mapping_v2


class _ValidationRegistry:
    def validate_strategy(self, _spec: object) -> tuple[object, ...]:
        return ()


def _strategy_mapping() -> dict[str, object]:
    price = {"node_type": "price_ref", "field": "close", "unit": "USD"}
    ema = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 50},
        "output": "series",
        "unit": "USD",
    }
    return {
        "schema_version": "v2.1",
        "strategy_id": "ema-cross-spy",
        "strategy_family": "ema_crossover",
        "strategy_name": "SPY EMA crossover",
        "symbol": "SPY",
        "market": "US_EQUITY",
        "timeframe": "1d",
        "session": {
            "timezone": "America/New_York",
            "regular_hours_only": True,
            "calendar_id": "XNYS",
        },
        "backtest_range": {"start": "2024-01-02", "end": "2024-12-31"},
        "initial_capital": {"amount": 100000, "currency": "USD"},
        "entry": {"node_type": "compare", "operator": "gt", "left": price, "right": ema},
        "exit": {"node_type": "compare", "operator": "lt", "left": price, "right": ema},
        "filters": [],
        "position_sizing": {"type": "fixed_fraction", "fraction": "1"},
        "stop": {"enabled": False},
        "target": {"enabled": False},
        "fill_timing": "next_bar_open",
        "data": {"source": "validated_local_cache_first"},
        "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
        "plugin": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


def _ir(mapping: dict[str, object] | None = None):
    result = normalize_strategy_spec(
        validate_strategy_mapping_v2(mapping or _strategy_mapping()),
        capability_registry=_ValidationRegistry(),
        source_config_hash="source-config-hash",
    )
    assert result.ir is not None
    return result.ir


def _inputs() -> dict[str, object]:
    return {
        "cost_profile_id": "cost.bps.v1",
        "corporate_action_profile_id": "corporate-actions.v1",
        "benchmark_protocol_id": "buy-and-hold.v1",
        "benchmark_protocol_version": "v1",
        "capability_snapshot_hash": "a" * 64,
        "normalizer_version": "v2.1",
    }


def _assumptions(mapping: dict[str, object] | None = None):
    from tv_quant.contracts.execution_assumptions import build_execution_assumptions

    ir = _ir(mapping)
    return build_execution_assumptions(ir, build_data_plan(ir, object()), _inputs())


def test_assumptions_contains_all_frozen_policy_and_version_fields() -> None:
    """The confirmation binding must expose every frozen policy and caller ID."""
    assumptions = _assumptions()

    assert assumptions.initial_capital_policy == "100000 USD"
    assert assumptions.fill_timing == "next_bar_open"
    assert dict(assumptions.session_policy) == {
        "calendar_id": "XNYS",
        "regular_hours_only": True,
        "timezone": "America/New_York",
    }
    assert assumptions.optimization_policy == "false"
    assert assumptions.report_language == "zh-CN"
    assert assumptions.cost_profile_id == "cost.bps.v1"
    assert assumptions.corporate_action_profile_id == "corporate-actions.v1"
    assert assumptions.benchmark_protocol_id == "buy-and-hold.v1"
    assert assumptions.benchmark_protocol_version == "v1"
    assert assumptions.capability_snapshot_hash == "a" * 64
    assert (assumptions.schema_version, assumptions.compiler_version, assumptions.normalizer_version) == (
        "v2.1", "v2.1", "v2.1"
    )


def test_assumptions_hash_accepts_only_execution_assumptions() -> None:
    """Hash ownership may not be bypassed with a caller-crafted mapping."""
    from tv_quant.contracts.execution_assumptions import assumptions_hash

    assert len(assumptions_hash(_assumptions())) == 64
    with pytest.raises(ValueError, match="ExecutionAssumptions required"):
        assumptions_hash({})  # type: ignore[arg-type]


def test_equivalent_decimal_policies_have_same_hash() -> None:
    """Exact decimal capital forms normalize to the same integer policy and hash."""
    from tv_quant.contracts.execution_assumptions import assumptions_hash

    decimal_mapping = deepcopy(_strategy_mapping())
    decimal_mapping["initial_capital"] = {"amount": Decimal("100000.0"), "currency": "USD"}

    assert assumptions_hash(_assumptions()) == assumptions_hash(_assumptions(decimal_mapping))


def test_missing_engine_and_plugin_are_explicit_not_implemented_or_null() -> None:
    """V2.1 must not imply an engine or plugin execution capability exists."""
    from tv_quant.contracts.execution_assumptions import execution_assumptions_payload

    payload = execution_assumptions_payload(_assumptions())

    assert payload["engine_status"] == "NOT_IMPLEMENTED"
    assert payload["plugin"] is None


def test_builder_requires_exact_caller_supplied_metadata_and_does_not_mutate_it() -> None:
    """Profiles and capability evidence are explicit input, never selected by the builder."""
    from tv_quant.contracts.execution_assumptions import build_execution_assumptions

    ir = _ir()
    plan = build_data_plan(ir, object())
    inputs = _inputs()
    before = deepcopy(inputs)
    assumptions = build_execution_assumptions(ir, plan, inputs)
    assert inputs == before
    assert assumptions.cost_profile_id == "cost.bps.v1"

    for invalid in ({}, {**_inputs(), "unexpected": "value"}, MappingProxyType(_inputs())):
        if isinstance(invalid, MappingProxyType):
            assert build_execution_assumptions(ir, plan, invalid).normalizer_version == "v2.1"
        else:
            with pytest.raises(ValueError):
                build_execution_assumptions(ir, plan, invalid)
    with pytest.raises(ValueError, match="mapping required"):
        build_execution_assumptions(ir, plan, object())


def test_payload_is_deterministic_fresh_and_session_is_deeply_immutable() -> None:
    """Hash payloads cannot retain caller mutability or order-dependent noise."""
    from tv_quant.contracts.execution_assumptions import (
        build_execution_assumptions,
        execution_assumptions_payload,
    )

    ir = _ir()
    plan = build_data_plan(ir, object())
    first = build_execution_assumptions(ir, plan, _inputs())
    reversed_inputs = dict(reversed(list(_inputs().items())))
    second = build_execution_assumptions(ir, plan, reversed_inputs)
    first_payload = execution_assumptions_payload(first)
    first_payload["session_policy"]["calendar_id"] = "XNAS"  # type: ignore[index]

    assert execution_assumptions_payload(first)["session_policy"]["calendar_id"] == "XNYS"  # type: ignore[index]
    assert execution_assumptions_payload(first) == execution_assumptions_payload(second)
    with pytest.raises(TypeError):
        first.session_policy["calendar_id"] = "XNAS"  # type: ignore[index]
