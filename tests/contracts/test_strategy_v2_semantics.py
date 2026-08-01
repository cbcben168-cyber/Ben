"""Semantic-model tests for validated ``quant-strategy/v2`` payloads."""

from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from tv_quant.contracts.strategy_v2 import (
    StrategySpecV2,
    ValidationIssue,
    validate_strategy_mapping_v2,
)


def _minimal_v2_mapping() -> dict[str, object]:
    """Return one complete V2 payload with explicit user semantics."""
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
        "position_sizing": {"type": "fixed_fraction", "fraction": "0.2500"},
        "stop": {"enabled": False},
        "target": {"enabled": False},
        "fill_timing": "next_bar_open",
        "data": {"source": "validated_local_cache_first"},
        "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
        "plugin": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


def test_semantic_model_preserves_source_payload():
    """The source copy is immutable and retains explicit user semantics."""
    payload = _minimal_v2_mapping()
    expected = deepcopy(payload)
    expected["filters"] = ()

    spec = validate_strategy_mapping_v2(payload)
    payload["data"]["source"] = "mutated-after-validation"  # type: ignore[index]

    assert spec.source_payload == expected
    assert spec.source_payload["position_sizing"]["fraction"] == "0.2500"
    with pytest.raises(TypeError):
        spec.source_payload["data"]["source"] = "mutation-attempt"


def test_semantic_dataclasses_reject_attribute_reassignment():
    """The semantic container and its validation issue are frozen dataclasses."""
    spec = validate_strategy_mapping_v2(_minimal_v2_mapping())
    issue = ValidationIssue(path="symbol", message="invalid symbol")

    assert isinstance(spec, StrategySpecV2)
    with pytest.raises(FrozenInstanceError):
        spec.symbol = "MSFT"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        issue.path = "market"  # type: ignore[misc]


def test_semantic_fields_are_immutable_and_source_payload_is_preserved():
    """Exact public fields are immutable while source input remains audit evidence."""
    payload = _minimal_v2_mapping()
    payload["symbol"] = "aapl"

    spec = validate_strategy_mapping_v2(payload)

    assert spec.symbol == "AAPL"
    assert spec.source_payload["symbol"] == "aapl"
    assert spec.position_sizing["fraction"] == "0.2500"
    assert isinstance(spec.position_sizing["fraction"], str)

    payload["data"]["source"] = "mutated-after-validation"  # type: ignore[index]
    payload["position_sizing"]["fraction"] = "0.5000"  # type: ignore[index]
    assert spec.data["source"] == "validated_local_cache_first"
    assert spec.position_sizing["fraction"] == "0.2500"
    with pytest.raises(TypeError):
        spec.position_sizing["fraction"] = "0.5000"


def test_semantic_model_validates_iso_range():
    """Invalid or unordered ranges cannot reach the semantic model."""
    payload = _minimal_v2_mapping()
    payload["backtest_range"] = {"start": "2024-12-31", "end": "2024-01-02"}

    with pytest.raises(ValueError, match="backtest_range"):
        validate_strategy_mapping_v2(payload)


def test_semantic_model_normalizes_symbol_case_only():
    """Only ticker casing changes; the rest of the validated payload is retained."""
    payload = _minimal_v2_mapping()
    payload["symbol"] = "aapl"

    spec = validate_strategy_mapping_v2(payload)

    assert spec.symbol == "AAPL"
    assert spec.source_payload["symbol"] == "aapl"


def test_semantic_model_rejects_non_us_equity():
    """The frozen semantic model accepts only the US-equity market contract."""
    payload = _minimal_v2_mapping()
    payload["market"] = "CRYPTO"

    with pytest.raises(ValueError, match="market"):
        validate_strategy_mapping_v2(payload)


def test_semantic_model_never_fills_position_sizing():
    """A missing user sizing decision remains an error, never an implicit default."""
    payload = _minimal_v2_mapping()
    del payload["position_sizing"]

    with pytest.raises(ValueError, match="missing required field: position_sizing"):
        validate_strategy_mapping_v2(payload)
