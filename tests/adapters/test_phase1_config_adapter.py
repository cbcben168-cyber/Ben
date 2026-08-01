from __future__ import annotations

import hashlib
import json
from pathlib import Path
from collections.abc import Mapping

import pytest

from tv_quant.adapters.phase1_config_adapter import (
    Phase1AdapterCapabilityBlocker,
    Phase1ToV2AdapterResult,
    adapt_phase1_to_v2,
)
from tv_quant.contracts.normalized_ir import NormalizedStrategyIR, normalize_strategy_spec
from tv_quant.contracts.strategy_v2 import StrategySpecV2, validate_strategy_mapping_v2
from tv_quant.run_manifest import canonical_hash


def _phase1_yaml(**overrides: object) -> str:
    payload: dict[str, object] = {
        "strategy_name": "ema_baseline",
        "asset_class": "equity",
        "symbol": "SPY",
        "benchmark": "buy_and_hold",
        "timeframe": "1d",
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "entry_rules": [
            {"type": "ema_crossover", "fast_period": 50, "slow_period": 200}
        ],
        "exit_rules": [{"type": "ema_crossunder"}],
        "position_sizing": {"type": "cash_limited_long_only"},
        "commission_model": {"type": "basis_points", "value": 5},
        "slippage_model": {"type": "basis_points", "value": 5},
        "fill_timing": "next_bar",
        "data_source": "validated_local_cache_first",
        "in_sample_period": None,
        "out_of_sample_period": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _write_phase1_config(tmp_path: Path, **overrides: object) -> Path:
    path = tmp_path / "phase1.yaml"
    path.write_text(_phase1_yaml(**overrides), encoding="utf-8")
    return path


def _jsonable(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


class _AcceptedRegistry:
    def validate_strategy(self, _spec: StrategySpecV2) -> tuple[object, ...]:
        return ()


def test_phase1_config_flows_to_v2_spec_then_ir(tmp_path: Path) -> None:
    """Removing the V2 validation or normalization step must break the adapter result."""
    result = adapt_phase1_to_v2(_write_phase1_config(tmp_path), adapter_version="phase1-to-v2/1")

    assert isinstance(result, Phase1ToV2AdapterResult)
    spec = validate_strategy_mapping_v2(result.generated_v2_payload)
    normalized = normalize_strategy_spec(
        spec,
        capability_registry=_AcceptedRegistry(),
        source_config_hash=result.source_phase1_config_hash,
    )
    assert isinstance(spec, StrategySpecV2)
    assert isinstance(normalized.ir, NormalizedStrategyIR)
    assert normalized.ir.symbol == "SPY"
    assert normalized.ir.entry.node_type == "cross_above"
    assert normalized.ir.exit.node_type == "cross_below"


def test_phase1_to_v2_result_preserves_source_and_generated_hashes(tmp_path: Path) -> None:
    """Changing either source bytes or generated V2 semantics must change its evidence hash."""
    path = _write_phase1_config(tmp_path)
    source_bytes = path.read_bytes()

    result = adapt_phase1_to_v2(path, adapter_version="phase1-to-v2/1")

    assert result.source_phase1_config_hash == hashlib.sha256(source_bytes).hexdigest()
    assert result.generated_v2_config_hash == canonical_hash(
        _jsonable(result.generated_v2_payload)
    )
    assert result.original_file_hash_after == result.original_file_hash_before


def test_adapter_records_version_warnings_unsupported_fields_and_unchanged_evidence(
    tmp_path: Path,
) -> None:
    """Omitting compatibility evidence would hide Phase 1 fields with no V2 equivalent."""
    result = adapt_phase1_to_v2(_write_phase1_config(tmp_path), adapter_version="phase1-to-v2/1.2.3")

    assert result.adapter_version == "phase1-to-v2/1.2.3"
    assert result.unsupported_fields == ("in_sample_period", "out_of_sample_period")
    assert result.conversion_warnings
    assert result.original_file_unchanged is True


def test_adapter_emits_explicit_filters_stop_target_fill_and_session(tmp_path: Path) -> None:
    """Dropping explicit V2 controls would permit dangerous implicit execution semantics."""
    result = adapt_phase1_to_v2(_write_phase1_config(tmp_path), adapter_version="phase1-to-v2/1")

    assert result.generated_v2_payload["filters"] == ()
    assert result.generated_v2_payload["stop"] == {"enabled": False}
    assert result.generated_v2_payload["target"] == {"enabled": False}
    assert result.generated_v2_payload["fill_timing"] == "next_bar_open"
    assert result.generated_v2_payload["session"] == {
        "timezone": "America/New_York",
        "regular_hours_only": True,
        "calendar_id": "XNYS",
    }
    assert result.generated_v2_payload["initial_capital"] == {
        "amount": 100000,
        "currency": "USD",
    }
    assert result.generated_v2_payload["position_sizing"] == {"type": "full_capital"}


def test_adapter_preserves_distinct_accepted_legacy_cost_values(tmp_path: Path) -> None:
    """Rounding a valid Phase 1 cost would silently change the generated V2 hash."""
    result = adapt_phase1_to_v2(
        _write_phase1_config(
            tmp_path,
            commission_model={"type": "basis_points", "value": 5.000000000000001},
        ),
        adapter_version="phase1-to-v2/1",
    )

    assert result.generated_v2_payload["data"]["legacy_costs"]["commission_bps"] == "5.000000000000001"


@pytest.mark.parametrize(
    ("field", "value", "status"),
    (
        ("symbol", "IWM", "STRATEGY_CAPABILITY_BLOCKER"),
        ("timeframe", "1h", "STRATEGY_CAPABILITY_BLOCKER"),
        ("entry_rules", [{"type": "rsi", "period": 2, "less_than": 10}], "STRATEGY_CAPABILITY_BLOCKER"),
        ("data_source", "yfinance", "DATA_CAPABILITY_BLOCKER"),
    ),
)
def test_adapter_rejects_non_ema_or_non_spy_qqq_capability(
    tmp_path: Path, field: str, value: object, status: str
) -> None:
    """Collapsing Phase 1 blocker identities would hide the failed pipeline stage."""
    with pytest.raises(Phase1AdapterCapabilityBlocker) as raised:
        adapt_phase1_to_v2(
            _write_phase1_config(tmp_path, **{field: value}),
            adapter_version="phase1-to-v2/1",
        )
    assert raised.value.status.value == status


def test_v2_to_phase1_adapter_is_not_part_of_v21() -> None:
    """A reverse converter would create an unapproved lossy migration surface."""
    import tv_quant.adapters.phase1_config_adapter as adapter

    assert not hasattr(adapter, "adapt_v2_to_phase1")


def test_original_phase1_file_bytes_remain_unchanged(tmp_path: Path) -> None:
    """An adapter that rewrites source configuration would destroy audit evidence."""
    path = _write_phase1_config(tmp_path)
    original = path.read_bytes()

    adapt_phase1_to_v2(path, adapter_version="phase1-to-v2/1")

    assert path.read_bytes() == original
