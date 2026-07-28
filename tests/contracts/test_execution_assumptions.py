"""Tests for the formal, immutable V2.1 execution-assumptions boundary."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from copy import deepcopy
from dataclasses import replace
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

    assert execution_assumptions_payload(first) == execution_assumptions_payload(second)
    with pytest.raises(TypeError):
        first.session_policy["calendar_id"] = "XNAS"  # type: ignore[index]
    with pytest.raises(TypeError):
        first_payload["session_policy"]["calendar_id"] = "XNAS"  # type: ignore[index]
    with pytest.raises(TypeError):
        first_payload["engine_status"] = "implemented"


@pytest.mark.parametrize("field", sorted(_inputs()))
def test_each_required_caller_metadata_field_is_individually_required(field: str) -> None:
    """Every profile, protocol, capability, and normalizer input is explicit."""
    from tv_quant.contracts.execution_assumptions import build_execution_assumptions

    ir = _ir()
    inputs = _inputs()
    inputs.pop(field)

    with pytest.raises(ValueError, match="exact caller metadata keys required"):
        build_execution_assumptions(ir, build_data_plan(ir, object()), inputs)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("cost_profile_id", "cost.other.v1"),
        ("corporate_action_profile_id", "corporate-actions.other.v1"),
        ("benchmark_protocol_id", "buy-and-hold.other.v1"),
        ("benchmark_protocol_version", "v2"),
        ("capability_snapshot_hash", "b" * 64),
    ),
)
def test_each_caller_controlled_identity_changes_the_hash(field: str, replacement: str) -> None:
    """Changing any caller-controlled profile/protocol/capability binding changes identity."""
    from tv_quant.contracts.execution_assumptions import assumptions_hash, build_execution_assumptions

    ir = _ir()
    changed_inputs = _inputs()
    changed_inputs[field] = replacement
    plan = build_data_plan(ir, object())

    assert assumptions_hash(build_execution_assumptions(ir, plan, _inputs())) != assumptions_hash(
        build_execution_assumptions(ir, plan, changed_inputs)
    )


def test_session_calendar_change_changes_hash_but_environment_noise_is_rejected() -> None:
    """The closed session schema binds only trading-session semantics."""
    from tv_quant.contracts.execution_assumptions import assumptions_hash

    baseline = _assumptions()
    changed = replace(baseline, session_policy={**baseline.session_policy, "calendar_id": "XNAS"})
    assert assumptions_hash(baseline) != assumptions_hash(changed)
    for noise_key in ("timestamp", "path", "pid", "mtime", "environment"):
        with pytest.raises(ValueError, match="exact keys required"):
            replace(baseline, session_policy={**baseline.session_policy, noise_key: "noise"})


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("initial_capital_policy", "1 USD"),
        ("fill_timing", "next_bar_close"),
        ("optimization_policy", "true"),
        ("report_language", "en-US"),
        ("schema_version", "v2.2"),
        ("compiler_version", "v2.2"),
        ("normalizer_version", "v2.2"),
        ("engine_status", "implemented"),
    ),
)
def test_frozen_policy_and_version_changes_are_rejected(field: str, replacement: str) -> None:
    """Pinned V2.1 policy/version values cannot be silently rebound."""
    with pytest.raises(ValueError):
        replace(_assumptions(), **{field: replacement})


@pytest.mark.parametrize(
    "session_policy",
    (
        {"timezone": "UTC", "regular_hours_only": True, "calendar_id": "XNYS"},
        {"timezone": "America/New_York", "regular_hours_only": False, "calendar_id": "XNYS"},
        {"timezone": "America/New_York", "regular_hours_only": True, "calendar_id": ""},
    ),
)
def test_frozen_session_policy_changes_are_rejected(session_policy: Mapping[str, object]) -> None:
    """Timezone and regular-hours policy are fixed, and calendar identity is required."""
    with pytest.raises(ValueError):
        replace(_assumptions(), session_policy=session_policy)


@pytest.mark.parametrize("snapshot", ("a" * 63, "A" * 64, "g" * 64))
def test_capability_snapshot_requires_exact_lowercase_sha256(snapshot: str) -> None:
    """Capability evidence is a stable identifier, not arbitrary caller text."""
    from tv_quant.contracts.execution_assumptions import build_execution_assumptions

    ir = _ir()
    inputs = _inputs()
    inputs["capability_snapshot_hash"] = snapshot
    with pytest.raises(ValueError, match="SHA-256"):
        build_execution_assumptions(ir, build_data_plan(ir, object()), inputs)


def test_caller_metadata_rejects_code_like_values() -> None:
    """Explicit profile/protocol fields cannot smuggle executable objects into the hash."""
    from tv_quant.contracts.execution_assumptions import build_execution_assumptions

    ir = _ir()
    inputs = _inputs()
    inputs["cost_profile_id"] = lambda: None
    with pytest.raises(ValueError, match="non-empty string required"):
        build_execution_assumptions(ir, build_data_plan(ir, object()), inputs)


@pytest.mark.parametrize("bad_value", (lambda: None, float("nan"), float("inf"), float("-inf")))
def test_code_like_and_noncanonical_numeric_values_are_rejected(bad_value: object) -> None:
    """Neither code-like values nor binary float/non-finite values enter the payload."""
    with pytest.raises(ValueError):
        replace(_assumptions(), session_policy={"timezone": "America/New_York", "regular_hours_only": True, "calendar_id": bad_value})


class _NoExecutionMapping(Mapping[str, object]):
    """Raises if the builder tries to treat metadata as a future registry object."""

    def __init__(self, values: Mapping[str, object]) -> None:
        self._values = values

    def __getitem__(self, key: str) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def snapshot_hash(self) -> object:
        raise AssertionError("builder must not invoke a capability registry")

    def validate_strategy(self) -> object:
        raise AssertionError("builder must not execute validation or a provider")


def test_builder_uses_metadata_as_data_without_external_execution_calls() -> None:
    """The narrow builder consumes only mapping values and starts no execution path."""
    from tv_quant.contracts.execution_assumptions import build_execution_assumptions

    ir = _ir()
    result = build_execution_assumptions(
        ir, build_data_plan(ir, object()), _NoExecutionMapping(_inputs())
    )

    assert result.capability_snapshot_hash == "a" * 64
