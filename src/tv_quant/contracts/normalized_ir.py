"""Immutable, deterministic V2 strategy normalization without execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any

from tv_quant.run_manifest import canonical_hash

from .ast_contract import (
    AstValidationError,
    PredicateExpression,
    ValidationIssue,
    ValueExpression,
    validate_ast,
)
from .numeric import canonical_decimal, canonical_integer
from .strategy_v2 import StrategySpecV2, validate_strategy_mapping_v2


_EXPLICIT_FIELDS = (
    "fill_timing",
    "optimization_allowed",
    "report_language",
    "session",
    "filters",
    "stop",
    "target",
)
_REQUIRED_FIELDS = (
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
    "fill_timing",
    "data",
    "benchmark",
    "plugin",
    "optimization_allowed",
    "report_language",
)
_DECIMAL_FIELDS = frozenset({"fraction", "risk_per_trade", "stop_distance"})


@dataclass(frozen=True, slots=True)
class NormalizedStrategyIR:
    """The executable-free, canonical representation of one V2 strategy."""

    schema_version: str
    strategy_id: str
    strategy_family: str
    strategy_name: str
    symbol: str
    market: str
    timeframe: str
    session: Mapping[str, object]
    backtest_range: Mapping[str, object]
    initial_capital: Mapping[str, object]
    entry: PredicateExpression
    exit: PredicateExpression
    filters: tuple[PredicateExpression, ...]
    position_sizing: Mapping[str, object]
    stop: Mapping[str, object]
    target: Mapping[str, object]
    data: Mapping[str, object]
    benchmark: Mapping[str, object]
    plugin: Mapping[str, object] | None
    fill_timing: str
    optimization_allowed: bool
    report_language: str
    compiler_version: str
    source_config_hash: str


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """A complete IR, or stable blocker issues with no partial IR."""

    ir: NormalizedStrategyIR | None
    issues: tuple[ValidationIssue, ...]


def _issue(code: str, path: str, message: str) -> ValidationIssue:
    pipeline_stage = "Stage 1" if code == "STRATEGY_CAPABILITY_BLOCKER" else "Stage 0"
    return ValidationIssue(
        code=code,
        path=path,
        severity="ERROR",
        message=message,
        recoverable=True,
        pipeline_stage=pipeline_stage,
        formal_result_eligible=False,
    )


def _freeze(value: object, path: str = "$") -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{path}: object keys must be strings")
        return MappingProxyType(
            {
                key: _freeze(value[key], f"{path}.{key}")
                for key in sorted(value)
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, f"{path}[{index}]") for index, item in enumerate(value))
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, float):
        raise ValueError(f"{path}: binary float values are not permitted")
    if isinstance(value, (int, Decimal)):
        return canonical_decimal(value, path)
    raise ValueError(f"{path}: non-JSON value is not permitted")


def _normalized_mapping(value: object, path: str, *, integer_fields: frozenset[str] = frozenset()) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path}: object required")
    if any(not isinstance(key, str) for key in value):
        raise ValueError(f"{path}: object keys must be strings")
    result: dict[str, object] = {}
    for key in sorted(value):
        item = value[key]
        item_path = f"{path}.{key}"
        if key in integer_fields:
            result[key] = canonical_integer(item, item_path)
        elif key in _DECIMAL_FIELDS:
            result[key] = canonical_decimal(item, item_path)
        else:
            result[key] = _freeze(item, item_path)
    return MappingProxyType(result)


def _explicit_fields(payload: Mapping[str, object]) -> ValidationIssue | None:
    for field in _EXPLICIT_FIELDS:
        if field not in payload:
            return _issue("CONFIG_VALIDATION_BLOCKER", field, "explicit field is required")
    if "position_sizing" not in payload:
        return _issue(
            "POSITION_SIZING_INPUT_BLOCKER",
            "position_sizing",
            "explicit position sizing is required",
        )
    for field in _REQUIRED_FIELDS:
        if field not in payload:
            return _issue("CONFIG_VALIDATION_BLOCKER", field, "required field is missing")
    return None


def _disabled_or_rule(value: object, path: str) -> Mapping[str, object]:
    normalized = _normalized_mapping(value, path)
    if normalized.get("enabled") is False:
        if set(normalized) != {"enabled"}:
            raise ValueError(f"{path}: disabled state cannot contain rule fields")
    elif normalized.get("enabled") is not True:
        raise ValueError(f"{path}.enabled: boolean required")
    return normalized


def _capability_issues(
    capability_registry: object,
    spec: StrategySpecV2,
) -> tuple[ValidationIssue, ...]:
    """Use the narrow validation hook without importing a future registry module."""
    validator = getattr(capability_registry, "validate_strategy", None)
    if not callable(validator):
        return (
            _issue(
                "STRATEGY_CAPABILITY_BLOCKER",
                "capability_registry",
                "validate_strategy capability gate is required",
            ),
        )
    issues = validator(spec)
    if not isinstance(issues, tuple) or not all(
        isinstance(issue, ValidationIssue) for issue in issues
    ):
        raise ValueError("capability_registry.validate_strategy must return issue tuple")
    return issues


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _strategy_spec_payload(spec: StrategySpecV2) -> Mapping[str, object]:
    """Reconstruct the frozen schema payload from the exact public fields."""
    return MappingProxyType(
        {
            "schema_version": spec.schema_version,
            "strategy_id": spec.strategy_id,
            "strategy_family": spec.strategy_family,
            "strategy_name": spec.strategy_name,
            "symbol": spec.symbol,
            "market": spec.market,
            "timeframe": spec.timeframe,
            "session": spec.session,
            "backtest_range": spec.backtest_range,
            "initial_capital": spec.initial_capital,
            "entry": spec.entry,
            "exit": spec.exit,
            "filters": spec.filters,
            "position_sizing": spec.position_sizing,
            "stop": spec.stop,
            "target": spec.target,
            "fill_timing": spec.source_payload.get("fill_timing"),
            "data": spec.data,
            "benchmark": spec.benchmark,
            "plugin": spec.plugin,
            "optimization_allowed": spec.optimization_allowed,
            "report_language": spec.report_language,
        }
    )


def normalize_strategy_spec(
    spec: StrategySpecV2,
    *,
    capability_registry: object,
    source_config_hash: str,
) -> NormalizationResult:
    """Normalize validated V2 input; this function never executes a strategy."""
    if not isinstance(spec, StrategySpecV2):
        return NormalizationResult(
            ir=None,
            issues=(_issue("CONFIG_VALIDATION_BLOCKER", "$", "StrategySpecV2 required"),),
        )
    if not isinstance(source_config_hash, str) or not source_config_hash:
        return NormalizationResult(
            ir=None,
            issues=(_issue("CONFIG_VALIDATION_BLOCKER", "source_config_hash", "non-empty string required"),),
        )

    payload = _strategy_spec_payload(spec)
    required_issue = _explicit_fields(payload)
    if required_issue is not None:
        return NormalizationResult(ir=None, issues=(required_issue,))

    try:
        validated_spec = validate_strategy_mapping_v2(_thaw(payload))
    except ValueError as error:
        path, _, message = str(error).partition(": ")
        return NormalizationResult(
            ir=None,
            issues=(_issue("CONFIG_VALIDATION_BLOCKER", path or "$", message or str(error)),),
        )
    payload = _strategy_spec_payload(validated_spec)

    try:
        initial_capital = _normalized_mapping(
            payload["initial_capital"], "initial_capital", integer_fields=frozenset({"amount"})
        )
        if initial_capital.get("amount") != 100000 or initial_capital.get("currency") != "USD":
            raise ValueError("initial_capital: must equal integer 100000 USD")
        entry = validate_ast(payload["entry"], PredicateExpression, "entry")
        exit_ = validate_ast(payload["exit"], PredicateExpression, "exit")
        raw_filters = payload["filters"]
        if not isinstance(raw_filters, (list, tuple)):
            raise ValueError("filters: array required")
        filters = tuple(
            validate_ast(node, PredicateExpression, f"filters[{index}]")
            for index, node in enumerate(raw_filters)
        )
        ir = NormalizedStrategyIR(
            schema_version=str(payload["schema_version"]),
            strategy_id=str(payload["strategy_id"]),
            strategy_family=str(payload["strategy_family"]),
            strategy_name=str(payload["strategy_name"]),
            symbol=str(payload["symbol"]).upper(),
            market=str(payload["market"]),
            timeframe=str(payload["timeframe"]),
            session=_normalized_mapping(payload["session"], "session"),
            backtest_range=_normalized_mapping(payload["backtest_range"], "backtest_range"),
            initial_capital=initial_capital,
            entry=entry,
            exit=exit_,
            filters=filters,
            position_sizing=_normalized_mapping(payload["position_sizing"], "position_sizing"),
            stop=_disabled_or_rule(payload["stop"], "stop"),
            target=_disabled_or_rule(payload["target"], "target"),
            data=_normalized_mapping(payload["data"], "data"),
            benchmark=_normalized_mapping(payload["benchmark"], "benchmark"),
            plugin=(
                None
                if payload["plugin"] is None
                else _normalized_mapping(payload["plugin"], "plugin")
            ),
            fill_timing=str(payload["fill_timing"]),
            optimization_allowed=payload["optimization_allowed"] is True,
            report_language=str(payload["report_language"]),
            compiler_version="v2.1",
            source_config_hash=source_config_hash,
        )
    except AstValidationError as error:
        return NormalizationResult(ir=None, issues=error.issues)
    except ValueError as error:
        path, _, message = str(error).partition(": ")
        return NormalizationResult(
            ir=None,
            issues=(_issue("CONFIG_VALIDATION_BLOCKER", path or "$", message or str(error)),),
        )

    try:
        issues = _capability_issues(capability_registry, validated_spec)
    except ValueError as error:
        return NormalizationResult(
            ir=None,
            issues=(_issue("CONFIG_VALIDATION_BLOCKER", "capability_registry", str(error)),),
        )
    if issues:
        return NormalizationResult(ir=None, issues=issues)
    return NormalizationResult(ir=ir, issues=())


def _payload_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _payload_value(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_payload_value(item) for item in value]
    if isinstance(value, ValueExpression):
        return {
            "node_id": value.node_id,
            "node_type": value.node_type,
            "output_type": value.output_type,
            "output": value.output,
            "unit": value.unit,
            "payload": _payload_value(value.payload),
        }
    if isinstance(value, PredicateExpression):
        return {
            "node_id": value.node_id,
            "node_type": value.node_type,
            "output_type": value.output_type,
            "payload": _payload_value(value.payload),
        }
    if isinstance(value, float) or callable(value):
        raise ValueError("IR contains forbidden non-canonical value")
    return value


def normalized_config_payload(ir: NormalizedStrategyIR) -> Mapping[str, object]:
    """Return the complete JSON-like canonical IR payload used for hashing."""
    if not isinstance(ir, NormalizedStrategyIR):
        raise ValueError("NormalizedStrategyIR required")
    return {
        field: _payload_value(getattr(ir, field))
        for field in NormalizedStrategyIR.__dataclass_fields__
    }


def normalized_config_hash(ir: NormalizedStrategyIR) -> str:
    """Hash the canonical IR through the existing manifest hash owner."""
    return canonical_hash(normalized_config_payload(ir))


__all__ = (
    "NormalizationResult",
    "NormalizedStrategyIR",
    "ValidationIssue",
    "normalize_strategy_spec",
    "normalized_config_hash",
    "normalized_config_payload",
)
