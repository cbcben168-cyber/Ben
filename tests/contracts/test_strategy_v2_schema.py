"""Offline contract tests for the quant-strategy/v2 loader."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from tv_quant.contracts.schema_contract import (
    ROOT_REQUIRED_FIELDS,
    schema_contract_snapshot,
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


def test_valid_minimal_v2_config_loads(tmp_path):
    """A complete explicit V2 mapping loads without network or Phase 1 parsing."""
    spec = load_strategy_spec_v2(_write_payload(tmp_path, _minimal_v2_mapping()))

    assert spec.payload["symbol"] == "AAPL"
    assert spec.payload["filters"] == ()


def test_schema_id_and_version_are_quant_strategy_v2_v21():
    """A wrong schema identity or version makes V2 configuration unrecognizable."""
    schema_path = Path(__file__).parents[2] / "schemas" / "quant-strategy-v2.schema.json"

    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["$id"] == "quant-strategy/v2"
    assert schema["properties"]["schema_version"]["enum"] == ["v2.1"]


def test_python_contract_and_json_schema_required_fields_match():
    """Schema drift could make a valid Python contract invalid to other consumers."""
    schema_path = Path(__file__).parents[2] / "schemas" / "quant-strategy-v2.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["required"] == list(ROOT_REQUIRED_FIELDS)
    assert schema["additionalProperties"] is False
    assert schema["$defs"] == schema_contract_snapshot()["ast_node_definitions"]


def test_symbol_schema_accepts_valid_us_equity_symbol_without_spy_qqq_cap():
    """Restricting V2 symbols to Phase 1 tickers would reject valid US equities."""
    payload = _minimal_v2_mapping()
    payload["symbol"] = "MSFT"

    assert validate_strategy_mapping_v2(payload).payload["symbol"] == "MSFT"


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
    assert validate_strategy_mapping_v2(valid).payload["filters"] == ()

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
