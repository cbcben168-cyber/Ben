"""Acceptance tests for the exact frozen V2.2 entry interfaces."""

from dataclasses import fields, is_dataclass
import inspect

import tv_quant.contracts as contracts
from tv_quant.adapters.phase1_config_adapter import (
    Phase1ToV2AdapterResult,
    adapt_phase1_to_v2,
)
from tv_quant.contracts import confirmation


def _field_names(value: type[object]) -> tuple[str, ...]:
    return tuple(field.name for field in fields(value))


def _parameter_shape(callable_: object) -> tuple[tuple[str, inspect._ParameterKind], ...]:
    return tuple(
        (parameter.name, parameter.kind)
        for parameter in inspect.signature(callable_).parameters.values()
    )


def test_frozen_public_types_are_concrete_root_exports_with_exact_fields() -> None:
    """Renaming fields or substituting a family label breaks the V2.2 entry gate."""
    assert _field_names(contracts.StrategySpecV2) == (
        "schema_version",
        "strategy_id",
        "strategy_family",
        "strategy_name",
        "symbol",
        "market",
        "timeframe",
        "session",
        "backtest_range",
        "initial_capital",
        "entry",
        "exit",
        "filters",
        "position_sizing",
        "stop",
        "target",
        "data",
        "benchmark",
        "plugin",
        "optimization_allowed",
        "report_language",
        "source_payload",
    )
    assert _field_names(Phase1ToV2AdapterResult) == (
        "generated_v2_payload",
        "source_phase1_config_hash",
        "adapter_version",
        "generated_v2_config_hash",
        "conversion_warnings",
        "unsupported_fields",
        "original_file_hash_before",
        "original_file_hash_after",
        "original_file_unchanged",
        "source_schema_version",
        "target_schema_version",
    )
    assert _field_names(contracts.ConfirmationGrant) == (
        "confirmation_request_id",
        "confirmation_token",
        "bound_config_hash",
        "bound_data_plan_hash",
        "bound_assumptions_hash",
        "issued_at",
        "expires_at",
        "single_use",
        "consumed_at",
    )

    for name in (
        "AuthorizedExecutionContext",
        "ArtifactContract",
        "StatusCodeRegistry",
    ):
        interface = getattr(contracts, name)
        assert name in contracts.__all__
        assert isinstance(interface, type)
        assert is_dataclass(interface)


def test_frozen_confirmation_and_adapter_signatures_are_exact() -> None:
    """Removing the store/request contracts would let later callers bypass the gate."""
    positional = inspect.Parameter.POSITIONAL_OR_KEYWORD
    keyword_only = inspect.Parameter.KEYWORD_ONLY

    assert _parameter_shape(confirmation.create_confirmation_request) == (
        ("ir", positional),
        ("data_plan", positional),
        ("assumptions", positional),
        ("generated_at", positional),
        ("expires_at", positional),
    )
    assert _parameter_shape(confirmation.issue_confirmation_grant) == (
        ("request", positional),
        ("approval", positional),
        ("store", positional),
        ("issued_at", positional),
    )
    assert _parameter_shape(confirmation.validate_and_consume) == (
        ("grant_token", positional),
        ("request", positional),
        ("ir", positional),
        ("data_plan", positional),
        ("assumptions", positional),
        ("store", positional),
        ("now", positional),
    )
    assert _parameter_shape(adapt_phase1_to_v2) == (
        ("phase1_config_path", positional),
        ("adapter_version", keyword_only),
    )
