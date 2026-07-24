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
