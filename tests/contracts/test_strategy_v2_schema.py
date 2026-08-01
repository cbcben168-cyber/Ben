"""Offline contract tests for the quant-strategy/v2 loader."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tv_quant.contracts.schema_contract import (
    AST_NODE_DEFINITIONS,
    ENUMS,
    ROOT_REQUIRED_FIELDS,
)
from tv_quant.contracts.strategy_v2 import (
    load_strategy_spec_v2,
    validate_strategy_mapping_v2,
)


def _minimal_v2_mapping() -> dict[str, object]:
    """Return a complete, hand-authored offline V2 contract fixture."""
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
        "symbol": "AAPL",
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
        "position_sizing": {"type": "full_capital"},
        "stop": {"enabled": False},
        "target": {"enabled": False},
        "fill_timing": "next_bar_open",
        "data": {"source": "validated_local_cache_first"},
        "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
        "plugin": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


def _write_payload(tmp_path, payload: object):
    path = tmp_path / "strategy-v2.yaml"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _schema() -> dict[str, object]:
    schema_path = Path(__file__).parents[2] / "schemas" / "quant-strategy-v2.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


def test_valid_minimal_v2_config_loads(tmp_path):
    """A complete explicit V2 mapping loads without network or Phase 1 parsing."""
    spec = load_strategy_spec_v2(_write_payload(tmp_path, _minimal_v2_mapping()))

    assert spec.symbol == "AAPL"
    assert spec.filters == ()


def test_schema_id_and_version_are_quant_strategy_v2_v21():
    """A wrong schema identity or version makes V2 configuration unrecognizable."""
    schema = _schema()

    assert schema["$id"] == "quant-strategy/v2"
    assert schema["properties"]["schema_version"]["enum"] == ["v2.1"]


def test_python_contract_and_json_schema_required_fields_match():
    """Schema drift could make a valid Python contract invalid to other consumers."""
    schema = _schema()

    assert schema["required"] == list(ROOT_REQUIRED_FIELDS)
    assert schema["additionalProperties"] is False
    for name, definition in AST_NODE_DEFINITIONS.items():
        rendered = schema["$defs"][name]

        assert rendered["type"] == "object"
        assert rendered["required"] == list(definition["required_fields"])
        assert rendered["additionalProperties"] is False
        assert rendered["properties"]["node_type"]["const"] == name
        assert rendered["x-contract-category"] == definition["category"]
        assert rendered["x-contract-output-type"] == definition["output_type"]


def test_symbol_schema_accepts_valid_us_equity_symbol_without_spy_qqq_cap():
    """Restricting V2 symbols to Phase 1 tickers would reject valid US equities."""
    payload = _minimal_v2_mapping()
    payload["symbol"] = "MSFT"

    assert validate_strategy_mapping_v2(payload).symbol == "MSFT"


def test_initial_capital_must_equal_100000_usd():
    """A different capital amount would violate the frozen V2.1 capital policy."""
    payload = _minimal_v2_mapping()
    payload["initial_capital"] = {"amount": 100001, "currency": "USD"}

    with pytest.raises(ValueError, match=r"initial_capital\.amount"):
        validate_strategy_mapping_v2(payload)


def test_missing_position_sizing_is_rejected_without_default():
    """Silently choosing a sizing policy changes user trading semantics."""
    payload = _minimal_v2_mapping()
    del payload["position_sizing"]

    with pytest.raises(ValueError, match="missing required field: position_sizing"):
        validate_strategy_mapping_v2(payload)


def test_each_explicit_root_field_is_required_without_normalization_default():
    """Dropping any root field must never be repaired by a normalization default."""
    for field in ROOT_REQUIRED_FIELDS:
        payload = _minimal_v2_mapping()
        del payload[field]

        with pytest.raises(ValueError, match=f"missing required field: {field}"):
            validate_strategy_mapping_v2(payload)


def test_invalid_enum_and_unknown_field_are_rejected():
    """Permissive enums or root fields would make the frozen contract ambiguous."""
    invalid_enum = _minimal_v2_mapping()
    invalid_enum["fill_timing"] = "next_bar"
    unknown_field = _minimal_v2_mapping()
    unknown_field["free_form_expression"] = "close > ema"

    with pytest.raises(ValueError, match="fill_timing"):
        validate_strategy_mapping_v2(invalid_enum)
    with pytest.raises(ValueError, match="unknown top-level configuration field"):
        validate_strategy_mapping_v2(unknown_field)


def test_disabled_stop_target_and_empty_filters_must_be_present():
    """Disabled states are input, not omitted or extensible implicit defaults."""
    valid = _minimal_v2_mapping()
    assert validate_strategy_mapping_v2(valid).filters == ()

    extra_disabled_field = _minimal_v2_mapping()
    extra_disabled_field["stop"] = {"enabled": False, "rule": "atr"}
    missing_target = _minimal_v2_mapping()
    del missing_target["target"]
    non_array_filters = _minimal_v2_mapping()
    non_array_filters["filters"] = None

    with pytest.raises(ValueError, match="stop"):
        validate_strategy_mapping_v2(extra_disabled_field)
    with pytest.raises(ValueError, match="missing required field: target"):
        validate_strategy_mapping_v2(missing_target)
    with pytest.raises(ValueError, match="filters"):
        validate_strategy_mapping_v2(non_array_filters)


def test_arbitrary_python_expression_field_is_rejected():
    """Accepting executable expression fields would violate the non-executable contract."""
    payload = _minimal_v2_mapping()
    payload["entry"] = deepcopy(payload["entry"])
    payload["entry"]["expression"] = "__import__('os').system('echo unsafe')"

    with pytest.raises(ValueError, match="entry"):
        validate_strategy_mapping_v2(payload)


def test_legacy_phase1_mapping_requires_explicit_v2_loader(tmp_path):
    """The V2 loader must not silently reinterpret a Phase 1 configuration."""
    legacy = {
        "strategy_name": "legacy EMA",
        "asset_class": "equity",
        "symbol": "SPY",
        "timeframe": "1d",
    }

    with pytest.raises(ValueError, match="missing required field: schema_version"):
        load_strategy_spec_v2(_write_payload(tmp_path, legacy))


def test_ast_runtime_enforces_frozen_enums_and_predicate_roots():
    """Ignoring Task 2 AST metadata permits invalid or value-root trading rules."""
    invalid_operator = _minimal_v2_mapping()
    invalid_operator["entry"] = deepcopy(invalid_operator["entry"])
    invalid_operator["entry"]["operator"] = "exec"
    invalid_indicator = _minimal_v2_mapping()
    invalid_indicator["entry"] = deepcopy(invalid_indicator["entry"])
    invalid_indicator["entry"]["right"]["name"] = "BOGUS"
    value_root = _minimal_v2_mapping()
    value_root["entry"] = {"node_type": "price_ref", "field": "close", "unit": "USD"}

    with pytest.raises(ValueError, match=r"entry\.operator"):
        validate_strategy_mapping_v2(invalid_operator)
    with pytest.raises(ValueError, match=r"entry\.right\.name"):
        validate_strategy_mapping_v2(invalid_indicator)
    with pytest.raises(ValueError, match="entry"):
        validate_strategy_mapping_v2(value_root)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", "not-a-number", 1.0])
def test_constant_nodes_require_task2_numeric_values(value):
    """Nonnumeric or binary-float constants cannot bypass canonical decimal validation."""
    payload = _minimal_v2_mapping()
    payload["entry"] = {
        "node_type": "compare",
        "operator": "gt",
        "left": {"node_type": "price_ref", "field": "close", "unit": "USD"},
        "right": {"node_type": "constant", "value": value, "unit": "USD"},
    }

    with pytest.raises(ValueError, match=r"entry\.right\.value"):
        validate_strategy_mapping_v2(payload)


@pytest.mark.parametrize("fraction", ["0", "-0.01", "1.01", 0, 2])
def test_fixed_fraction_is_strictly_greater_than_zero_and_at_most_one(fraction):
    """Zero, negative, or leveraged fractions violate the frozen sizing policy."""
    payload = _minimal_v2_mapping()
    payload["position_sizing"] = {"type": "fixed_fraction", "fraction": fraction}

    with pytest.raises(ValueError, match=r"position_sizing\.fraction"):
        validate_strategy_mapping_v2(payload)


@pytest.mark.parametrize(
    ("value", "unit"),
    [("007", "string"), (True, "boolean"), (False, "boolean")],
)
def test_constant_value_kind_is_selected_by_declared_unit(value, unit):
    """String and boolean constants must not pass through numeric canonicalization."""
    payload = _minimal_v2_mapping()
    payload["entry"] = {
        "node_type": "compare",
        "operator": "eq",
        "left": {"node_type": "constant", "value": value, "unit": unit},
        "right": {"node_type": "constant", "value": value, "unit": unit},
    }

    spec = validate_strategy_mapping_v2(payload)

    assert spec.entry["left"]["value"] is value


def test_checked_schema_distinguishes_constant_kinds_and_bounds_fraction():
    """External schema consumers must enforce the same constant and sizing semantics."""
    schema = _schema()
    constant = schema["$defs"]["constant"]
    fraction = schema["$defs"]["position_sizing"]["oneOf"][1]["properties"]["fraction"]

    assert constant["allOf"] == [
        {
            "if": {"properties": {"unit": {"const": "string"}}},
            "then": {"properties": {"value": {"type": "string"}}},
        },
        {
            "if": {"properties": {"unit": {"const": "boolean"}}},
            "then": {"properties": {"value": {"type": "boolean"}}},
        },
        {
            "if": {
                "properties": {
                    "unit": {"not": {"enum": ["string", "boolean"]}}
                }
            },
            "then": {"properties": {"value": {"$ref": "#/$defs/decimal_value"}}},
        },
    ]
    assert fraction == {"$ref": "#/$defs/positive_fraction"}


def test_json_schema_uses_operative_ast_and_disabled_state_definitions():
    """Generic nested objects would leave external consumers without contract enforcement."""
    schema = _schema()
    definitions = schema["$defs"]

    assert schema["properties"]["entry"] == {"$ref": "#/$defs/predicate_expression"}
    assert schema["properties"]["exit"] == {"$ref": "#/$defs/predicate_expression"}
    assert schema["properties"]["filters"]["items"] == {
        "$ref": "#/$defs/predicate_expression"
    }
    assert schema["properties"]["stop"] == {"$ref": "#/$defs/disabled_or_rule"}
    assert schema["properties"]["target"] == {"$ref": "#/$defs/disabled_or_rule"}
    assert definitions["disabled_or_rule"]["oneOf"][0]["properties"]["enabled"] == {
        "const": False
    }
    assert definitions["predicate_expression"]["oneOf"]
    assert definitions["value_expression"]["oneOf"]


def test_json_schema_enums_and_ast_contract_metadata_match_task2():
    """Every frozen Task 2 enum must constrain the matching external schema location."""
    schema = _schema()
    properties = schema["properties"]

    for field in ("schema_version", "market", "timeframe", "fill_timing", "report_language"):
        assert properties[field]["enum"] == list(ENUMS[field])
    assert schema["$defs"]["indicator_ref"]["properties"]["name"]["enum"] == list(
        ENUMS["indicator_name"]
    )
    assert schema["$defs"]["compare"]["properties"]["operator"]["enum"] == list(
        ENUMS["comparison_operator"]
    )
