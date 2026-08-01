"""Immutable Python source definitions for the V2 strategy schema contract."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from .ast_contract import AST_NODE_DEFINITIONS


ROOT_REQUIRED_FIELDS = (
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

ENUMS = MappingProxyType(
    {
        "schema_version": ("v2.1",),
        "market": ("US_EQUITY",),
        "timeframe": ("1d", "15m", "30m", "60m"),
        "fill_timing": ("next_bar_open",),
        "report_language": ("zh-CN",),
        "indicator_name": (
            "EMA",
            "SMA",
            "RSI",
            "MACD",
            "ATR",
            "BOLLINGER",
            "DONCHIAN",
            "VOLUME_SMA",
            "RELATIVE_VOLUME",
        ),
        "comparison_operator": ("gt", "gte", "lt", "lte", "eq", "neq"),
    }
)


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value


def schema_contract_snapshot() -> dict[str, object]:
    """Return JSON-compatible data derived directly from immutable definitions."""
    return {
        "root_required_fields": list(ROOT_REQUIRED_FIELDS),
        "enums": _json_value(ENUMS),
        "ast_node_definitions": _json_value(AST_NODE_DEFINITIONS),
        "schema_definitions": _schema_definitions(),
    }


def _object_definition(
    name: str,
    properties: dict[str, object],
) -> dict[str, object]:
    contract = AST_NODE_DEFINITIONS[name]
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(contract["required_fields"]),
        "properties": properties,
        "x-contract-category": contract["category"],
        "x-contract-output-type": contract["output_type"],
    }


def _schema_definitions() -> dict[str, object]:
    decimal_value = {
        "oneOf": [
            {"type": "integer"},
            {
                "type": "string",
                "pattern": r"^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
            },
        ]
    }
    definitions: dict[str, object] = {
        "decimal_value": decimal_value,
        "positive_fraction": {
            "oneOf": [
                {"type": "integer", "minimum": 1, "maximum": 1},
                {
                    "type": "string",
                    "pattern": r"^(?:0\.(?:0*[1-9][0-9]*)|1(?:\.0+)?)$",
                },
            ]
        },
        "session": {
            "type": "object",
            "additionalProperties": False,
            "required": ["timezone", "regular_hours_only", "calendar_id"],
            "properties": {
                "timezone": {"const": "America/New_York"},
                "regular_hours_only": {"const": True},
                "calendar_id": {"type": "string", "minLength": 1},
            },
        },
        "backtest_range": {
            "type": "object",
            "additionalProperties": False,
            "required": ["start", "end"],
            "properties": {
                "start": {"type": "string", "format": "date"},
                "end": {"type": "string", "format": "date"},
            },
        },
        "initial_capital": {
            "type": "object",
            "additionalProperties": False,
            "required": ["amount", "currency"],
            "properties": {"amount": {"const": 100000}, "currency": {"const": "USD"}},
        },
    }
    definitions["indicator_ref"] = _object_definition(
        "indicator_ref",
        {
            "node_type": {"const": "indicator_ref"},
            "name": {"enum": list(ENUMS["indicator_name"])},
            "parameters": {"type": "object"},
            "output": {"type": "string", "minLength": 1},
            "unit": {"type": "string", "minLength": 1},
        },
    )
    constant = _object_definition(
        "constant",
        {
            "node_type": {"const": "constant"},
            "value": {},
            "unit": {"type": "string", "minLength": 1},
        },
    )
    constant["allOf"] = [
        {
            "if": {"properties": {"unit": {"const": "string"}}},
            "then": {"properties": {"value": {"type": "string"}}},
        },
        {
            "if": {"properties": {"unit": {"const": "boolean"}}},
            "then": {"properties": {"value": {"type": "boolean"}}},
        },
        {
            "if": {"properties": {"unit": {"not": {"enum": ["string", "boolean"]}}}},
            "then": {"properties": {"value": {"$ref": "#/$defs/decimal_value"}}},
        },
    ]
    definitions["constant"] = constant
    for name, field in (("price_ref", "close"), ("volume_ref", "volume")):
        definitions[name] = _object_definition(
            name,
            {
                "node_type": {"const": name},
                "field": {"type": "string", "minLength": 1},
                "unit": {"type": "string", "minLength": 1},
            },
        )
    definitions["compare"] = _object_definition(
        "compare",
        {
            "node_type": {"const": "compare"},
            "operator": {"enum": list(ENUMS["comparison_operator"])},
            "left": {"$ref": "#/$defs/value_expression"},
            "right": {"$ref": "#/$defs/value_expression"},
        },
    )
    for name in ("cross_above", "cross_below"):
        definitions[name] = _object_definition(
            name,
            {
                "node_type": {"const": name},
                "left": {"$ref": "#/$defs/value_expression"},
                "right": {"$ref": "#/$defs/value_expression"},
            },
        )
    for name in ("all", "any"):
        definitions[name] = _object_definition(
            name,
            {
                "node_type": {"const": name},
                "children": {
                    "type": "array",
                    "minItems": 1,
                    "items": {"$ref": "#/$defs/predicate_expression"},
                },
            },
        )
    definitions["not"] = _object_definition(
        "not",
        {
            "node_type": {"const": "not"},
            "child": {"$ref": "#/$defs/predicate_expression"},
        },
    )
    definitions["value_expression"] = {
        "oneOf": [{"$ref": f"#/$defs/{name}"} for name in ("indicator_ref", "constant", "price_ref", "volume_ref")]
    }
    definitions["predicate_expression"] = {
        "oneOf": [{"$ref": f"#/$defs/{name}"} for name in ("compare", "cross_above", "cross_below", "all", "any", "not")]
    }
    definitions["disabled_or_rule"] = {
        "oneOf": [
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["enabled"],
                "properties": {"enabled": {"const": False}},
            },
            {
                "type": "object",
                "additionalProperties": False,
                "required": ["enabled", "rule", "unit"],
                "properties": {
                    "enabled": {"const": True},
                    "rule": {"type": "string", "minLength": 1},
                    "unit": {"type": "string", "minLength": 1},
                },
            },
        ]
    }
    definitions["position_sizing"] = {
        "oneOf": [
            {"type": "object", "additionalProperties": False, "required": ["type"], "properties": {"type": {"const": "full_capital"}}},
            {"type": "object", "additionalProperties": False, "required": ["type", "fraction"], "properties": {"type": {"const": "fixed_fraction"}, "fraction": {"$ref": "#/$defs/positive_fraction"}}},
            {"type": "object", "additionalProperties": False, "required": ["type", "risk_per_trade", "stop_distance"], "properties": {"type": {"const": "risk_based"}, "risk_per_trade": {"$ref": "#/$defs/decimal_value"}, "stop_distance": {"$ref": "#/$defs/decimal_value"}}},
        ]
    }
    definitions["benchmark"] = {"type": "object", "additionalProperties": False, "required": ["type", "symbol"], "properties": {"type": {"const": "buy_and_hold"}, "symbol": {"const": "same_as_strategy"}}}
    definitions["plugin"] = {"oneOf": [{"type": "null"}, {"type": "object", "additionalProperties": False, "required": ["name", "version", "source_hash"], "properties": {field: {"type": "string", "minLength": 1} for field in ("name", "version", "source_hash")}}]}
    return definitions


def render_json_schema() -> dict[str, Any]:
    """Render the deterministic Draft 2020-12 schema input from the definitions."""
    properties: dict[str, object] = {
        "schema_version": {"enum": list(ENUMS["schema_version"])},
        "strategy_id": {"type": "string", "minLength": 1},
        "strategy_family": {"type": "string", "minLength": 1},
        "strategy_name": {"type": "string", "minLength": 1},
        "symbol": {"type": "string", "pattern": "^[A-Z][A-Z0-9.-]{0,9}$"},
        "market": {"enum": list(ENUMS["market"])},
        "timeframe": {"enum": list(ENUMS["timeframe"])},
        "session": {"$ref": "#/$defs/session"},
        "backtest_range": {"$ref": "#/$defs/backtest_range"},
        "initial_capital": {"$ref": "#/$defs/initial_capital"},
        "entry": {"$ref": "#/$defs/predicate_expression"},
        "exit": {"$ref": "#/$defs/predicate_expression"},
        "filters": {"type": "array", "items": {"$ref": "#/$defs/predicate_expression"}},
        "position_sizing": {"$ref": "#/$defs/position_sizing"},
        "stop": {"$ref": "#/$defs/disabled_or_rule"},
        "target": {"$ref": "#/$defs/disabled_or_rule"},
        "fill_timing": {"enum": list(ENUMS["fill_timing"])},
        "data": {"type": "object"},
        "benchmark": {"$ref": "#/$defs/benchmark"},
        "plugin": {"$ref": "#/$defs/plugin"},
        "optimization_allowed": {"const": False},
        "report_language": {"enum": list(ENUMS["report_language"])},
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "quant-strategy/v2",
        "title": "quant-strategy/v2 contract",
        "description": "Deterministic external contract derived from the frozen V2 root, enum, and AST definitions. Runtime validation is contract-equivalent, not a complete Draft 2020-12 evaluator.",
        "type": "object",
        "additionalProperties": False,
        "required": list(ROOT_REQUIRED_FIELDS),
        "properties": properties,
        "$defs": _schema_definitions(),
    }
