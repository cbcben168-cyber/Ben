from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tv_quant.pipeline_models import CapabilityStatus
from tv_quant.strategy_spec import check_capabilities, validate_strategy_mapping

from tests.pipeline.helpers import valid_payload, write_rsi_config


@pytest.mark.parametrize(
    ("field", "value", "status"),
    [
        ("symbol", "IWM", CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER),
        ("timeframe", "30m", CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER),
        ("optimization_allowed", True, CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER),
        ("data_source", "ibkr", CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER),
    ],
)
def test_unsupported_capability_is_blocked(field, value, status):
    payload = valid_payload()
    payload[field] = value
    result = check_capabilities(validate_strategy_mapping(payload))
    assert result.status is status


def test_rsi_is_blocked_without_approximation():
    payload = valid_payload()
    payload["entry_rules"] = [{"type": "rsi", "period": 2, "less_than": 10}]
    result = check_capabilities(validate_strategy_mapping(payload))
    assert result.status is CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER
    assert "EMA" in " ".join(result.reasons)


def test_yfinance_requires_explicit_smoke_test_mode():
    payload = valid_payload()
    payload["data_source"] = "yfinance"
    spec = validate_strategy_mapping(payload)
    assert check_capabilities(spec).status is CapabilityStatus.DATA_CAPABILITY_BLOCKER
    result = check_capabilities(spec, allow_smoke_test_data=True)
    assert result.status is CapabilityStatus.SUPPORTED
    assert "SMOKE_TEST_DATA_ONLY" in result.required_data
    assert "validated" not in " ".join(result.required_data).lower()


@pytest.mark.parametrize("asset_class", ["options", "option-chain"])
def test_option_data_requests_are_data_capability_blockers(asset_class):
    payload = valid_payload()
    payload["asset_class"] = asset_class

    result = check_capabilities(validate_strategy_mapping(payload))

    assert result.status is CapabilityStatus.DATA_CAPABILITY_BLOCKER
    assert "option" in " ".join(result.reasons).lower()


def test_rsi_blocker_prevents_future_pipeline_side_effects(monkeypatch):
    pipeline = pytest.importorskip("tv_quant.research_pipeline")
    calls = []

    def fail_refresh(*args, **kwargs):
        calls.append("refresh")
        raise AssertionError("refresh must not run for a strategy blocker")

    def fail_backtest(*args, **kwargs):
        calls.append("backtest")
        raise AssertionError("backtest must not run for a strategy blocker")

    monkeypatch.setattr(pipeline, "run_backtest", fail_backtest)
    with TemporaryDirectory() as temporary_directory:
        data_root = Path(temporary_directory)
        result = pipeline.run_pipeline(
            write_rsi_config(data_root),
            pipeline.PipelineOptions(data_root=data_root),
            refresh_data=fail_refresh,
        )

    assert result.status == CapabilityStatus.STRATEGY_CAPABILITY_BLOCKER.value
    assert calls == []
