"""Typed, immutable validation contract for V2 value and predicate ASTs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import re
from types import MappingProxyType
from typing import Any

from .numeric import canonical_decimal, canonical_integer


MAX_AST_DEPTH = 16
MAX_AST_NODES = 128

_VALUE_CATEGORY = "ValueExpression"
_PREDICATE_CATEGORY = "PredicateExpression"
_VALUE_OUTPUT = "value"
_PREDICATE_OUTPUT = "predicate"
_SERIES_OUTPUT = "series"
_SCALAR_OUTPUT = "scalar"

_PRICE_FIELDS = frozenset({"open", "high", "low", "close", "adjusted_close"})
_VOLUME_FIELDS = frozenset({"volume"})
_PRICE_UNIT = "USD"
_VOLUME_UNIT = "shares"
_COMPARABLE_UNITS = frozenset(
    {_PRICE_UNIT, "percentage", "ratio", "integer-period"}
)
_STRING_UNIT = "string"
_BOOLEAN_UNIT = "boolean"
_ALLOWED_UNITS = _COMPARABLE_UNITS | {_VOLUME_UNIT, _STRING_UNIT, _BOOLEAN_UNIT}
_FORBIDDEN_PARAMETER_TERMS = frozenset(
    {
        "account",
        "broker",
        "callable",
        "class",
        "code",
        "dynamic",
        "endpoint",
        "exec",
        "expression",
        "file",
        "filesystem",
        "function",
        "host",
        "import",
        "module",
        "network",
        "order",
        "path",
        "provider",
        "python",
        "socket",
        "uri",
        "url",
        "webhook",
    }
)
_NON_FINITE_TEXT = frozenset({"NaN", "Infinity", "-Infinity"})
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _node(
    category: str,
    required_fields: tuple[str, ...],
    output_type: str,
) -> Mapping[str, object]:
    return MappingProxyType(
        {
            "category": category,
            "required_fields": required_fields,
            "output_type": output_type,
            "additional_properties": False,
        }
    )


AST_NODE_DEFINITIONS = MappingProxyType(
    {
        "indicator_ref": _node(
            _VALUE_CATEGORY,
            ("node_type", "name", "parameters", "output", "unit"),
            _VALUE_OUTPUT,
        ),
        "constant": _node(
            _VALUE_CATEGORY, ("node_type", "value", "unit"), _VALUE_OUTPUT
        ),
        "price_ref": _node(
            _VALUE_CATEGORY, ("node_type", "field", "unit"), _VALUE_OUTPUT
        ),
        "volume_ref": _node(
            _VALUE_CATEGORY, ("node_type", "field", "unit"), _VALUE_OUTPUT
        ),
        "compare": _node(
            _PREDICATE_CATEGORY,
            ("node_type", "operator", "left", "right"),
            _PREDICATE_OUTPUT,
        ),
        "cross_above": _node(
            _PREDICATE_CATEGORY,
            ("node_type", "left", "right"),
            _PREDICATE_OUTPUT,
        ),
        "cross_below": _node(
            _PREDICATE_CATEGORY,
            ("node_type", "left", "right"),
            _PREDICATE_OUTPUT,
        ),
        "all": _node(
            _PREDICATE_CATEGORY, ("node_type", "children"), _PREDICATE_OUTPUT
        ),
        "any": _node(
            _PREDICATE_CATEGORY, ("node_type", "children"), _PREDICATE_OUTPUT
        ),
        "not": _node(
            _PREDICATE_CATEGORY, ("node_type", "child"), _PREDICATE_OUTPUT
        ),
    }
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One immutable AST validation failure."""

    code: str
    path: str
    severity: str
    message: str
    recoverable: bool
    pipeline_stage: str
    formal_result_eligible: bool


class AstValidationError(ValueError):
    """Validation failure carrying stable immutable issue records."""

    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        first = issues[0]
        super().__init__(f"{first.path}: {first.message}")


@dataclass(frozen=True, slots=True)
class ValueExpression:
    """Validated immutable value node."""

    node_id: str
    node_type: str
    output_type: str
    output: str
    unit: str
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PredicateExpression:
    """Validated immutable boolean node."""

    node_id: str
    node_type: str
    output_type: str
    payload: Mapping[str, object]


@dataclass(slots=True)
class _ValidationState:
    nodes: int = 0


def _issue(path: str, message: str, *, complexity: bool = False) -> None:
    code = "AST_COMPLEXITY_BLOCKER" if complexity else "CONFIG_VALIDATION_BLOCKER"
    raise AstValidationError(
        (
            ValidationIssue(
                code=code,
                path=path,
                severity="ERROR",
                message=message,
                recoverable=True,
                pipeline_stage="Stage 0",
                formal_result_eligible=False,
            ),
        )
    )


def _expected_category(expected_type: object) -> str:
    categories = {
        ValueExpression: _VALUE_CATEGORY,
        PredicateExpression: _PREDICATE_CATEGORY,
        _VALUE_CATEGORY: _VALUE_CATEGORY,
        _PREDICATE_CATEGORY: _PREDICATE_CATEGORY,
        _VALUE_OUTPUT: _VALUE_CATEGORY,
        _PREDICATE_OUTPUT: _PREDICATE_CATEGORY,
    }
    try:
        return categories[expected_type]
    except (KeyError, TypeError) as error:
        raise ValueError(
            "expected_type must be ValueExpression or PredicateExpression"
        ) from error


def node_id(
    node: Mapping[str, object],
    traversal_path: str | Sequence[int],
) -> str:
    """Return a stable non-hash ID from node type and canonical preorder path."""
    if not isinstance(node, Mapping):
        raise ValueError("node must be a mapping")
    node_type = node.get("node_type")
    if not isinstance(node_type, str) or node_type not in AST_NODE_DEFINITIONS:
        raise ValueError("node.node_type must be a registered AST node type")
    if isinstance(traversal_path, str):
        path_text = traversal_path
    elif isinstance(traversal_path, Sequence) and all(
        isinstance(part, int) and not isinstance(part, bool) and part >= 0
        for part in traversal_path
    ):
        path_text = ".".join(str(part) for part in traversal_path)
    else:
        raise ValueError("traversal_path must be a string or non-negative integer path")
    return f"{node_type}@{path_text or 'root'}"


def _enter(
    node: Mapping[str, object],
    path: str,
    depth: int,
    state: _ValidationState,
) -> str:
    state.nodes += 1
    if depth > MAX_AST_DEPTH:
        _issue(path, f"maximum AST depth {MAX_AST_DEPTH} exceeded", complexity=True)
    if state.nodes > MAX_AST_NODES:
        _issue(
            path,
            f"maximum AST node count {MAX_AST_NODES} exceeded",
            complexity=True,
        )
    return node_id(node, (state.nodes - 1,))


def _mapping(node: object, path: str) -> Mapping[str, object]:
    if not isinstance(node, Mapping):
        _issue(path, "AST node object required")
    if any(not isinstance(key, str) for key in node):
        _issue(path, "AST node keys must be strings")
    return node


def _definition(
    node: Mapping[str, object],
    expected_category: str,
    path: str,
) -> tuple[str, Mapping[str, object]]:
    node_type = node.get("node_type")
    if not isinstance(node_type, str) or node_type not in AST_NODE_DEFINITIONS:
        _issue(f"{path}.node_type", "unknown AST node type")
    definition = AST_NODE_DEFINITIONS[node_type]
    if definition["category"] != expected_category:
        _issue(path, f"{expected_category} required")
    fields = set(definition["required_fields"])
    unknown = sorted(set(node) - fields)
    if unknown:
        _issue(path, "unknown field(s): " + ", ".join(unknown))
    missing = sorted(fields - set(node))
    if missing:
        _issue(path, "missing required field(s): " + ", ".join(missing))
    return node_type, definition


def _enum_values(name: str) -> tuple[str, ...]:
    # Lazy import avoids a cycle because schema_contract owns the shared enums.
    from .schema_contract import ENUMS

    return ENUMS[name]


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        _issue(path, "non-empty string required")
    return value


def _unit(value: object, path: str) -> str:
    unit = _string(value, path)
    if unit not in _ALLOWED_UNITS:
        _issue(path, "unsupported explicit unit")
    return unit


def _is_forbidden_parameter_key(key: str) -> bool:
    normalized = _CAMEL_CASE_BOUNDARY.sub("_", key).lower()
    collapsed = re.sub(r"[^a-z0-9]", "", normalized)
    return any(term in collapsed for term in _FORBIDDEN_PARAMETER_TERMS)


def _canonical_parameter_number(value: object, path: str, key: str | None) -> object:
    try:
        if key is not None and key.lower().replace("-", "_").endswith("period"):
            return canonical_integer(value, path)
        return canonical_decimal(value, path)
    except ValueError as error:
        _issue(path, str(error).partition(": ")[2] or str(error))


def _freeze_parameter(value: object, path: str, key: str | None = None) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(item_key, str) for item_key in value):
            _issue(path, "parameter keys must be strings")
        frozen: dict[str, object] = {}
        for item_key in sorted(value):
            if _is_forbidden_parameter_key(item_key):
                _issue(f"{path}.{item_key}", "dynamic/path/network field is not permitted")
            frozen[item_key] = _freeze_parameter(
                value[item_key], f"{path}.{item_key}", item_key
            )
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_parameter(item, f"{path}[{index}]", key)
            for index, item in enumerate(value)
        )
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, str):
        if value in _NON_FINITE_TEXT:
            _issue(path, "non-finite decimal value")
        if key is not None and key.lower().replace("-", "_").endswith("period"):
            return _canonical_parameter_number(value, path, key)
        return value
    if isinstance(value, (int, Decimal)) and not isinstance(value, bool):
        return _canonical_parameter_number(value, path, key)
    if isinstance(value, float):
        _canonical_parameter_number(value, path, key)
    _issue(path, "non-JSON or executable parameter value is not permitted")


def _value(
    node: object,
    path: str,
    depth: int,
    state: _ValidationState,
) -> ValueExpression:
    mapping = _mapping(node, path)
    node_type, _ = _definition(mapping, _VALUE_CATEGORY, path)
    identifier = _enter(mapping, path, depth, state)
    payload: dict[str, object] = {"node_type": node_type}

    if node_type == "indicator_ref":
        name = _string(mapping["name"], f"{path}.name")
        if name not in _enum_values("indicator_name"):
            _issue(f"{path}.name", "unknown structural indicator name")
        parameters = mapping["parameters"]
        if not isinstance(parameters, Mapping):
            _issue(f"{path}.parameters", "object required")
        output = _string(mapping["output"], f"{path}.output")
        if output != _SERIES_OUTPUT:
            _issue(f"{path}.output", "indicator_ref output must equal series")
        unit = _unit(mapping["unit"], f"{path}.unit")
        payload.update(
            {
                "name": name,
                "parameters": _freeze_parameter(parameters, f"{path}.parameters"),
                "output": output,
                "unit": unit,
            }
        )
    elif node_type == "constant":
        unit = _unit(mapping["unit"], f"{path}.unit")
        source_value = mapping["value"]
        if unit == _STRING_UNIT:
            if not isinstance(source_value, str):
                _issue(f"{path}.value", "string constant required for string unit")
            value = source_value
        elif unit == _BOOLEAN_UNIT:
            if not isinstance(source_value, bool):
                _issue(f"{path}.value", "boolean constant required for boolean unit")
            value = source_value
        else:
            if isinstance(source_value, bool):
                _issue(f"{path}.value", "numeric constant required for declared unit")
            try:
                value = (
                    canonical_integer(source_value, f"{path}.value")
                    if unit == "integer-period"
                    else canonical_decimal(source_value, f"{path}.value")
                )
            except ValueError as error:
                _issue(f"{path}.value", str(error).partition(": ")[2] or str(error))
        output = _SCALAR_OUTPUT
        payload.update({"value": value, "unit": unit})
    elif node_type == "price_ref":
        field = _string(mapping["field"], f"{path}.field")
        if field not in _PRICE_FIELDS:
            _issue(f"{path}.field", "unsupported price field")
        unit = _string(mapping["unit"], f"{path}.unit")
        if unit != _PRICE_UNIT:
            _issue(f"{path}.unit", f"price_ref unit must equal {_PRICE_UNIT}")
        output = _SERIES_OUTPUT
        payload.update({"field": field, "unit": unit})
    else:
        field = _string(mapping["field"], f"{path}.field")
        if field not in _VOLUME_FIELDS:
            _issue(f"{path}.field", "volume_ref field must equal volume")
        unit = _string(mapping["unit"], f"{path}.unit")
        if unit != _VOLUME_UNIT:
            _issue(f"{path}.unit", f"volume_ref unit must equal {_VOLUME_UNIT}")
        output = _SERIES_OUTPUT
        payload.update({"field": field, "unit": unit})

    return ValueExpression(
        node_id=identifier,
        node_type=node_type,
        output_type=_VALUE_OUTPUT,
        output=output,
        unit=unit,
        payload=MappingProxyType(payload),
    )


def _predicate(
    node: object,
    path: str,
    depth: int,
    state: _ValidationState,
) -> PredicateExpression:
    mapping = _mapping(node, path)
    node_type, _ = _definition(mapping, _PREDICATE_CATEGORY, path)
    identifier = _enter(mapping, path, depth, state)
    payload: dict[str, object] = {"node_type": node_type}

    if node_type in {"compare", "cross_above", "cross_below"}:
        if node_type == "compare":
            operator = _string(mapping["operator"], f"{path}.operator")
            if operator not in _enum_values("comparison_operator"):
                _issue(f"{path}.operator", "unknown comparison operator")
            payload["operator"] = operator
        left = _value(mapping["left"], f"{path}.left", depth + 1, state)
        right = _value(mapping["right"], f"{path}.right", depth + 1, state)
        if left.unit != right.unit:
            _issue(path, f"incompatible units: {left.unit} and {right.unit}")
        if node_type == "compare" and left.unit in {_STRING_UNIT, _BOOLEAN_UNIT}:
            if operator not in {"eq", "neq"}:
                _issue(path, "string/boolean comparisons require eq or neq")
        elif left.unit not in _COMPARABLE_UNITS:
            _issue(path, f"unit {left.unit} is not comparable")
        if node_type != "compare" and (
            left.output != _SERIES_OUTPUT or right.output != _SERIES_OUTPUT
        ):
            _issue(path, "cross operands must both produce series values")
        payload.update({"left": left, "right": right})
    elif node_type in {"all", "any"}:
        children = mapping["children"]
        if not isinstance(children, (list, tuple)) or not children:
            _issue(f"{path}.children", "non-empty array required")
        payload["children"] = tuple(
            _predicate(child, f"{path}.children[{index}]", depth + 1, state)
            for index, child in enumerate(children)
        )
    else:
        payload["child"] = _predicate(
            mapping["child"], f"{path}.child", depth + 1, state
        )

    return PredicateExpression(
        node_id=identifier,
        node_type=node_type,
        output_type=_PREDICATE_OUTPUT,
        payload=MappingProxyType(payload),
    )


def validate_ast(
    node: Mapping[str, Any],
    expected_type: object,
    path: str,
) -> ValueExpression | PredicateExpression:
    """Validate one AST root without executing indicators or arbitrary code."""
    category = _expected_category(expected_type)
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    state = _ValidationState()
    if category == _VALUE_CATEGORY:
        return _value(node, path, 1, state)
    return _predicate(node, path, 1, state)


__all__ = (
    "AST_NODE_DEFINITIONS",
    "MAX_AST_DEPTH",
    "MAX_AST_NODES",
    "AstValidationError",
    "PredicateExpression",
    "ValidationIssue",
    "ValueExpression",
    "node_id",
    "validate_ast",
)
