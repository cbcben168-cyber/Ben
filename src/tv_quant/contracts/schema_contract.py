"""Immutable Python source definitions for the V2 strategy schema contract."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any


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
            "ValueExpression", ("node_type", "name", "parameters", "output", "unit"), "value"
        ),
        "constant": _node("ValueExpression", ("node_type", "value", "unit"), "value"),
        "price_ref": _node("ValueExpression", ("node_type", "field", "unit"), "value"),
        "volume_ref": _node("ValueExpression", ("node_type", "field", "unit"), "value"),
        "compare": _node(
            "PredicateExpression", ("node_type", "operator", "left", "right"), "predicate"
        ),
        "cross_above": _node("PredicateExpression", ("node_type", "left", "right"), "predicate"),
        "cross_below": _node("PredicateExpression", ("node_type", "left", "right"), "predicate"),
        "all": _node("PredicateExpression", ("node_type", "children"), "predicate"),
        "any": _node("PredicateExpression", ("node_type", "children"), "predicate"),
        "not": _node("PredicateExpression", ("node_type", "child"), "predicate"),
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
    }


def render_json_schema() -> dict[str, Any]:
    """Render the deterministic Draft 2020-12 schema input from the definitions."""
    snapshot = schema_contract_snapshot()
    properties: dict[str, object] = {field: {} for field in ROOT_REQUIRED_FIELDS}
    for field, values in snapshot["enums"].items():
        if field in properties:
            properties[field] = {"enum": values}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "quant-strategy/v2",
        "type": "object",
        "additionalProperties": False,
        "required": snapshot["root_required_fields"],
        "properties": properties,
        "$defs": snapshot["ast_node_definitions"],
    }
