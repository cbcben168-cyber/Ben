"""Tests for deterministic, immutable V2 normalized strategy IR."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from decimal import Decimal
from types import MappingProxyType
from typing import Any

import pytest

from tv_quant.contracts.normalized_ir import (
    NormalizationResult,
    ValidationIssue,
    normalize_strategy_spec,
    normalized_config_hash,
    normalized_config_payload,
)
from tv_quant.contracts.strategy_v2 import StrategySpecV2, validate_strategy_mapping_v2


def _mapping() -> dict[str, object]:
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
        "strategy_id": "ema-cross-aapl",
        "strategy_family": "ema_crossover",
        "strategy_name": "AAPL EMA crossover",
        "symbol": "aapl",
        "market": "US_EQUITY",
        "timeframe": "1d",
        "session": {
            "timezone": "America/New_York",
            "regular_hours_only": True,
            "calendar_id": "XNYS",
        },
        "backtest_range": {"start": "2024-01-02", "end": "2024-12-31"},
        "initial_capital": {"amount": 100000, "currency": "USD"},
        "entry": {
            "node_type": "compare",
            "operator": "gt",
            "left": price,
            "right": ema,
        },
        "exit": {
            "node_type": "compare",
            "operator": "lt",
            "left": price,
            "right": ema,
        },
        "filters": [],
        "position_sizing": {"type": "fixed_fraction", "fraction": "1.00"},
        "stop": {"enabled": False},
        "target": {"enabled": False},
        "fill_timing": "next_bar_open",
        "data": {"source": "validated_local_cache_first"},
        "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
        "plugin": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


class _FixedRegistry:
    def __init__(self, issues: tuple[ValidationIssue, ...] = ()) -> None:
        self.issues = issues

    def validate_strategy(self, _spec: StrategySpecV2) -> tuple[ValidationIssue, ...]:
        return self.issues


@pytest.fixture
def registry() -> _FixedRegistry:
    return _FixedRegistry()


@pytest.fixture
def spec() -> StrategySpecV2:
    return validate_strategy_mapping_v2(_mapping())


def _result(spec: StrategySpecV2, registry: _FixedRegistry) -> NormalizationResult:
    return normalize_strategy_spec(
        spec,
        capability_registry=registry,
        source_config_hash="source-config-hash",
    )


@pytest.mark.parametrize(
    "field",
    ("fill_timing", "optimization_allowed", "report_language", "session", "filters", "stop", "target"),
)
def test_missing_explicit_fields_never_become_normalization_defaults(
    spec: StrategySpecV2, registry: _FixedRegistry, field: str
) -> None:
    payload = dict(spec.payload)
    payload.pop(field)
    incomplete = StrategySpecV2(
        payload=MappingProxyType(payload),
        source_payload=MappingProxyType(payload),
        symbol=spec.symbol,
    )

    result = _result(incomplete, registry)

    assert result.ir is None
    assert result.issues[0].code == "CONFIG_VALIDATION_BLOCKER"
    assert result.issues[0].path == field


def test_normalization_requires_position_sizing(
    spec: StrategySpecV2, registry: _FixedRegistry
) -> None:
    payload = dict(spec.payload)
    payload.pop("position_sizing")
    incomplete = StrategySpecV2(
        payload=MappingProxyType(payload),
        source_payload=MappingProxyType(payload),
        symbol=spec.symbol,
    )

    result = _result(incomplete, registry)

    assert result.ir is None
    assert result.issues[0].code == "POSITION_SIZING_INPUT_BLOCKER"
    assert result.issues[0].path == "position_sizing"


def test_identical_semantics_produce_identical_ir_and_hash(registry: _FixedRegistry) -> None:
    left = _mapping()
    right = {key: left[key] for key in reversed(tuple(left))}

    left_ir = _result(validate_strategy_mapping_v2(left), registry).ir
    right_ir = _result(validate_strategy_mapping_v2(right), registry).ir

    assert left_ir == right_ir
    assert left_ir is not None
    assert right_ir is not None
    assert normalized_config_hash(left_ir) == normalized_config_hash(right_ir)


def test_decimal_numeric_forms_produce_identical_hash(registry: _FixedRegistry) -> None:
    left = _mapping()
    right = deepcopy(left)
    right["position_sizing"] = {"type": "fixed_fraction", "fraction": Decimal("1.0")}
    right_entry = right["entry"]
    assert isinstance(right_entry, dict)
    right_ema = right_entry["right"]
    assert isinstance(right_ema, dict)
    right_ema["parameters"] = {"period": "50.00"}

    left_ir = _result(validate_strategy_mapping_v2(left), registry).ir
    right_ir = _result(validate_strategy_mapping_v2(right), registry).ir

    assert left_ir is not None
    assert right_ir is not None
    assert normalized_config_hash(left_ir) == normalized_config_hash(right_ir)


def test_different_semantics_change_hash(spec: StrategySpecV2, registry: _FixedRegistry) -> None:
    changed = _mapping()
    changed["strategy_name"] = "AAPL EMA crossover revised"

    left_ir = _result(spec, registry).ir
    right_ir = _result(validate_strategy_mapping_v2(changed), registry).ir

    assert left_ir is not None
    assert right_ir is not None
    assert normalized_config_hash(left_ir) != normalized_config_hash(right_ir)


def test_ir_preserves_explicit_disabled_stop_target_and_empty_filters(
    spec: StrategySpecV2, registry: _FixedRegistry
) -> None:
    result = _result(spec, registry)

    assert result.ir is not None
    assert result.ir.stop == {"enabled": False}
    assert result.ir.target == {"enabled": False}
    assert result.ir.filters == ()
    with pytest.raises(TypeError):
        result.ir.stop["enabled"] = True  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        result.ir.symbol = "MSFT"  # type: ignore[misc]


def test_node_ids_and_units_are_canonical(spec: StrategySpecV2, registry: _FixedRegistry) -> None:
    result = _result(spec, registry)

    assert result.ir is not None
    assert result.ir.entry.node_id == "compare@0"
    assert result.ir.entry.payload["left"].node_id == "price_ref@1"
    assert result.ir.entry.payload["right"].node_id == "indicator_ref@2"
    assert result.ir.entry.payload["left"].unit == "USD"
    assert result.ir.position_sizing["fraction"] == "1"


def test_ir_contains_no_float_callable_or_python_source(
    spec: StrategySpecV2, registry: _FixedRegistry
) -> None:
    result = _result(spec, registry)

    assert result.ir is not None
    payload = normalized_config_payload(result.ir)

    def visit(value: Any) -> None:
        assert not isinstance(value, float)
        assert not callable(value)
        if isinstance(value, dict):
            for child in value.values():
                visit(child)
        elif isinstance(value, tuple):
            for child in value:
                visit(child)

    visit(payload)
    assert "source_payload" not in payload


def test_unsupported_capability_reports_issue_without_execution(spec: StrategySpecV2) -> None:
    registry = _FixedRegistry(
        (
            ValidationIssue(
                code="STRATEGY_CAPABILITY_BLOCKER",
                path="entry.right.name",
                severity="ERROR",
                message="EMA capability is not registered",
                recoverable=True,
                pipeline_stage="Stage 1",
                formal_result_eligible=False,
            ),
        )
    )

    result = _result(spec, registry)

    assert result.ir is None
    assert result.issues == registry.issues
