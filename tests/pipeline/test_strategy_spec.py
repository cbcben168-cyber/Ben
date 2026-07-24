from datetime import date
from pathlib import Path

import pytest

from tv_quant.pipeline_models import StrategySpec
from tv_quant.strategy_spec import (
    check_capabilities,
    load_strategy_spec,
    validate_strategy_mapping,
)

from tests.pipeline.helpers import valid_payload


def test_defaults_and_ema_mapping_are_deterministic():
    spec = validate_strategy_mapping(valid_payload())
    assert isinstance(spec, StrategySpec)
    assert spec.symbol == "SPY"
    assert spec.fill_timing == "next_bar"
    assert spec.optimization_allowed is False
    assert spec.report_language == "zh-CN"
    assert spec.data_source == "validated_local_cache_first"
    assert spec.commission_bps == 5
    assert spec.slippage_bps == 5
    assert spec.start_date == date(2020, 1, 1)


def test_checked_in_ema_yaml_is_supported():
    spec = load_strategy_spec(Path("config/strategies/ema_baseline.yaml"))
    assert spec.strategy_name == "ema_baseline"
    assert check_capabilities(spec).status.value == "SUPPORTED"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda data: data.pop("symbol"), "missing required field: symbol"),
        (lambda data: data.update({"start_date": "2025-01-01"}), "start_date must precede end_date"),
        (lambda data: data.update({"commission_model": {"type": "basis_points", "value": -1}}), "commission"),
        (lambda data: data.update({"initial_capital": 0}), "initial_capital"),
    ],
)
def test_invalid_strategy_config_is_rejected(mutator, message):
    payload = valid_payload()
    mutator(payload)
    with pytest.raises(ValueError, match=message):
        validate_strategy_mapping(payload)


@pytest.mark.parametrize(
    ("field", "value", "blocker"),
    [
        ("asset_class", "crypto", "asset_class 'equity' only"),
        ("symbol", "IWM", "symbols SPY and QQQ only"),
        ("timeframe", "1h", "timeframe '1d' only"),
        ("benchmark", "custom", "benchmark 'buy_and_hold' only"),
        ("fill_timing", "same_close", "fill_timing 'next_bar' only"),
        ("data_source", "remote_api", "data_source 'validated_local_cache_first'"),
        ("optimization_allowed", True, "optimization_allowed to be false"),
        ("report_language", "en-US", "report_language 'zh-CN' only"),
    ],
)
def test_phase_one_boundary_violations_are_capability_blockers(field, value, blocker):
    payload = valid_payload()
    payload[field] = value

    result = check_capabilities(validate_strategy_mapping(payload))

    assert result.status.value != "SUPPORTED"
    assert any(blocker in reason for reason in result.reasons)


@pytest.mark.parametrize("field", ["in_sample_period", "out_of_sample_period"])
def test_unparsed_non_null_periods_are_rejected(field):
    payload = valid_payload()
    payload[field] = ["2020-01-01", "2020-12-31"]

    with pytest.raises(ValueError, match=f"{field} is not supported"):
        validate_strategy_mapping(payload)


@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_optimization_allowed_must_be_a_boolean(value):
    payload = valid_payload()
    payload["optimization_allowed"] = value

    with pytest.raises(ValueError, match="optimization_allowed must be a boolean"):
        validate_strategy_mapping(payload)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("initial_capital", float("nan"), "initial_capital must be a finite number"),
        ("initial_capital", float("inf"), "initial_capital must be a finite number"),
        ("initial_capital", "100000", "initial_capital must be a finite number"),
        ("commission_model", {"type": "basis_points", "value": float("nan")}, "commission_model must be a finite number"),
        ("commission_model", {"type": "basis_points", "value": float("inf")}, "commission_model must be a finite number"),
        ("commission_model", {"type": "basis_points", "value": "5"}, "commission_model must be a finite number"),
        ("slippage_model", {"type": "basis_points", "value": float("nan")}, "slippage_model must be a finite number"),
        ("slippage_model", {"type": "basis_points", "value": float("inf")}, "slippage_model must be a finite number"),
        ("slippage_model", {"type": "basis_points", "value": "5"}, "slippage_model must be a finite number"),
    ],
)
def test_numeric_configuration_must_be_finite_numbers(field, value, message):
    payload = valid_payload()
    payload[field] = value

    with pytest.raises(ValueError, match=message):
        validate_strategy_mapping(payload)
