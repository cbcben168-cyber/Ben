"""Contract-equivalent loader for the frozen ``quant-strategy/v2`` input."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

import yaml

from .numeric import canonical_decimal, canonical_integer
from .schema_contract import AST_NODE_DEFINITIONS, ENUMS, ROOT_REQUIRED_FIELDS


_SYMBOL = re.compile(r"[A-Z][A-Z0-9.-]{0,9}\Z")
_JSON_SCALAR_TYPES = (str, bool, type(None), int, Decimal)


@dataclass(frozen=True, slots=True)
class StrategySpecV2:
    """Minimal immutable V2 configuration after contract-equivalent validation."""

    payload: Mapping[str, Any]


def _error(path: str, message: str) -> ValueError:
    return ValueError(f"{path}: {message}")


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise _error(path, "object required")
    return value


def _exact_fields(mapping: Mapping[str, object], path: str, fields: set[str]) -> None:
    unknown = sorted(str(key) for key in set(mapping) - fields)
    if unknown:
        raise _error(path, "unknown field(s): " + ", ".join(unknown))
    missing = sorted(fields - set(mapping))
    if missing:
        raise _error(path, "missing required field(s): " + ", ".join(missing))


def _enum(field: str, value: object, path: str | None = None) -> None:
    if value not in ENUMS[field]:
        raise _error(path or field, "must be one of " + ", ".join(ENUMS[field]))


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise _error(path, "non-empty string required")
    return value


def _safe_value(value: object, path: str) -> None:
    """Reject non-JSON values and binary floats before they reach the contract."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise _error(path, "object keys must be strings")
            _safe_value(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _safe_value(item, f"{path}[{index}]")
        return
    if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool):
        canonical_decimal(value, path)
        return
    if not isinstance(value, _JSON_SCALAR_TYPES):
        raise _error(path, "non-JSON value is not permitted")


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _validate_session(value: object) -> None:
    session = _mapping(value, "session")
    _exact_fields(session, "session", {"timezone", "regular_hours_only", "calendar_id"})
    if session["timezone"] != "America/New_York":
        raise _error("session.timezone", "must equal America/New_York")
    if session["regular_hours_only"] is not True:
        raise _error("session.regular_hours_only", "must equal true")
    _string(session["calendar_id"], "session.calendar_id")


def _validate_backtest_range(value: object) -> None:
    backtest_range = _mapping(value, "backtest_range")
    _exact_fields(backtest_range, "backtest_range", {"start", "end"})
    try:
        start = date.fromisoformat(_string(backtest_range["start"], "backtest_range.start"))
        end = date.fromisoformat(_string(backtest_range["end"], "backtest_range.end"))
    except ValueError as error:
        raise _error("backtest_range", "ISO dates required") from error
    if start >= end:
        raise _error("backtest_range", "start must precede end")


def _validate_capital(value: object) -> None:
    capital = _mapping(value, "initial_capital")
    _exact_fields(capital, "initial_capital", {"amount", "currency"})
    amount = canonical_integer(capital["amount"], "initial_capital.amount")
    if amount != 100000:
        raise _error("initial_capital.amount", "must equal 100000")
    if capital["currency"] != "USD":
        raise _error("initial_capital.currency", "must equal USD")


def _validate_ast(value: object, path: str, category: str) -> None:
    node = _mapping(value, path)
    node_type = node.get("node_type")
    if not isinstance(node_type, str) or node_type not in AST_NODE_DEFINITIONS:
        raise _error(f"{path}.node_type", "unknown AST node type")
    definition = AST_NODE_DEFINITIONS[node_type]
    expected_output_type = {
        "ValueExpression": "value",
        "PredicateExpression": "predicate",
    }[category]
    if (
        definition["category"] != category
        or definition["output_type"] != expected_output_type
    ):
        raise _error(path, f"{category} with {expected_output_type} output required")
    allowed = set(definition["required_fields"])
    _exact_fields(node, path, allowed)
    for field in definition["required_fields"]:
        _safe_value(node[field], f"{path}.{field}")
    if node_type == "indicator_ref":
        _enum("indicator_name", node["name"], f"{path}.name")
    elif node_type == "constant":
        canonical_decimal(node["value"], f"{path}.value")
    if node_type in {"compare", "cross_above", "cross_below"}:
        if node_type == "compare":
            _enum("comparison_operator", node["operator"], f"{path}.operator")
        _validate_ast(node["left"], f"{path}.left", "ValueExpression")
        _validate_ast(node["right"], f"{path}.right", "ValueExpression")
    elif node_type in {"all", "any"}:
        children = node["children"]
        if not isinstance(children, list) or not children:
            raise _error(f"{path}.children", "non-empty array required")
        for index, child in enumerate(children):
            _validate_ast(child, f"{path}.children[{index}]", "PredicateExpression")
    elif node_type == "not":
        _validate_ast(node["child"], f"{path}.child", "PredicateExpression")


def _validate_disabled_or_rule(value: object, path: str) -> None:
    state = _mapping(value, path)
    if state.get("enabled") is False:
        _exact_fields(state, path, {"enabled"})
        return
    _exact_fields(state, path, {"enabled", "rule", "unit"})
    if state["enabled"] is not True:
        raise _error(f"{path}.enabled", "boolean required")
    _string(state["rule"], f"{path}.rule")
    _string(state["unit"], f"{path}.unit")


def _validate_position_sizing(value: object) -> None:
    sizing = _mapping(value, "position_sizing")
    sizing_type = sizing.get("type")
    fields_by_type = {
        "full_capital": {"type"},
        "fixed_fraction": {"type", "fraction"},
        "risk_based": {"type", "risk_per_trade", "stop_distance"},
    }
    if sizing_type not in fields_by_type:
        raise _error("position_sizing.type", "unsupported position sizing type")
    _exact_fields(sizing, "position_sizing", fields_by_type[sizing_type])
    for field in fields_by_type[sizing_type] - {"type"}:
        canonical_decimal(sizing[field], f"position_sizing.{field}")


def _validate_benchmark(value: object) -> None:
    benchmark = _mapping(value, "benchmark")
    _exact_fields(benchmark, "benchmark", {"type", "symbol"})
    if benchmark["type"] != "buy_and_hold":
        raise _error("benchmark.type", "must equal buy_and_hold")
    if benchmark["symbol"] != "same_as_strategy":
        raise _error("benchmark.symbol", "must equal same_as_strategy")


def _validate_plugin(value: object) -> None:
    if value is None:
        return
    plugin = _mapping(value, "plugin")
    _exact_fields(plugin, "plugin", {"name", "version", "source_hash"})
    for field in ("name", "version", "source_hash"):
        _string(plugin[field], f"plugin.{field}")


def validate_strategy_mapping_v2(payload: Mapping[str, Any]) -> StrategySpecV2:
    """Validate the V2 input contract without claiming full JSON Schema execution."""
    if not isinstance(payload, Mapping):
        raise ValueError("strategy config must be a YAML mapping")
    for field in ROOT_REQUIRED_FIELDS:
        if field not in payload:
            raise ValueError(f"missing required field: {field}")
    unknown = sorted(str(key) for key in set(payload) - set(ROOT_REQUIRED_FIELDS))
    if unknown:
        raise ValueError("unknown top-level configuration field(s): " + ", ".join(unknown))
    _safe_value(payload, "$")

    for field in ("schema_version", "market", "timeframe", "fill_timing", "report_language"):
        _enum(field, payload[field])
    for field in ("strategy_id", "strategy_family", "strategy_name"):
        _string(payload[field], field)
    symbol = _string(payload["symbol"], "symbol")
    if not _SYMBOL.fullmatch(symbol):
        raise _error("symbol", "valid US equity symbol required")
    _validate_session(payload["session"])
    _validate_backtest_range(payload["backtest_range"])
    _validate_capital(payload["initial_capital"])
    _validate_ast(payload["entry"], "entry", "PredicateExpression")
    _validate_ast(payload["exit"], "exit", "PredicateExpression")
    filters = payload["filters"]
    if not isinstance(filters, list):
        raise _error("filters", "array required")
    for index, item in enumerate(filters):
        _validate_ast(item, f"filters[{index}]", "PredicateExpression")
    _validate_position_sizing(payload["position_sizing"])
    _validate_disabled_or_rule(payload["stop"], "stop")
    _validate_disabled_or_rule(payload["target"], "target")
    if not isinstance(payload["data"], Mapping):
        raise _error("data", "object required")
    _validate_benchmark(payload["benchmark"])
    _validate_plugin(payload["plugin"])
    if payload["optimization_allowed"] is not False:
        raise _error("optimization_allowed", "must equal false")

    return StrategySpecV2(payload=_freeze(dict(payload)))


def load_strategy_spec_v2(path: Path) -> StrategySpecV2:
    """Load one explicit V2 YAML mapping; legacy Phase 1 mappings remain invalid."""
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError("strategy config must be a YAML mapping")
    return validate_strategy_mapping_v2(payload)
