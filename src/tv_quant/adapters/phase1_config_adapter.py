"""One-way, auditable Phase 1 configuration translation into V2.1."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from tv_quant.contracts.normalized_ir import NormalizedStrategyIR, normalize_strategy_spec
from tv_quant.contracts.strategy_v2 import StrategySpecV2, validate_strategy_mapping_v2
from tv_quant.pipeline_models import CapabilityStatus
from tv_quant.run_manifest import canonical_hash, sha256_file
from tv_quant.strategy_spec import check_capabilities, load_strategy_spec


_UNSUPPORTED_NULL_FIELDS = ("in_sample_period", "out_of_sample_period")


@dataclass(frozen=True, slots=True)
class Phase1ToV2AdapterResult:
    """Immutable translation evidence and the validated V2/IR representations."""

    source_path: Path
    source_hash: str
    source_hash_after: str
    adapter_version: str
    v2_payload: Mapping[str, object]
    generated_v2_hash: str
    strategy_spec_v2: StrategySpecV2
    normalized_ir: NormalizedStrategyIR
    warnings: tuple[str, ...]
    unsupported_fields: tuple[str, ...]
    source_bytes_unchanged: bool


class Phase1AdapterCapabilityBlocker(ValueError):
    """Preserve the Phase 1 capability-gate status at the adapter boundary."""

    def __init__(self, status: CapabilityStatus, reasons: tuple[str, ...]) -> None:
        self.status = status
        self.reasons = reasons
        super().__init__(f"{status.value}: " + "; ".join(reasons))


class _SingleValidatedSpecRegistry:
    """Allow normalization of only the V2 spec that passed the Phase 1 gate."""

    def __init__(self, expected_spec: StrategySpecV2) -> None:
        self._expected_spec = expected_spec

    def validate_strategy(self, spec: StrategySpecV2) -> tuple[object, ...]:
        if spec != self._expected_spec:
            raise ValueError("adapter received an unexpected V2 specification")
        return ()


def _basis_points_text(value: float) -> str:
    """Keep legacy costs explicit without introducing binary floats into V2."""
    return str(value)


def _v2_payload(spec) -> dict[str, object]:
    if spec.initial_capital != 100000:
        raise ValueError("Phase 1 adapter requires initial_capital equal to 100000 USD")

    fast_ema = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 50},
        "output": "series",
        "unit": "USD",
    }
    slow_ema = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 200},
        "output": "series",
        "unit": "USD",
    }
    return {
        "schema_version": "v2.1",
        "strategy_id": f"phase1-{spec.strategy_name}-{spec.symbol}".lower(),
        "strategy_family": "ema_crossover",
        "strategy_name": spec.strategy_name,
        "symbol": spec.symbol,
        "market": "US_EQUITY",
        "timeframe": "1d",
        "session": {
            "timezone": "America/New_York",
            "regular_hours_only": True,
            "calendar_id": "XNYS",
        },
        "backtest_range": {
            "start": spec.start_date.isoformat(),
            "end": spec.end_date.isoformat(),
        },
        "initial_capital": {"amount": 100000, "currency": "USD"},
        "entry": {"node_type": "cross_above", "left": fast_ema, "right": slow_ema},
        "exit": {"node_type": "cross_below", "left": fast_ema, "right": slow_ema},
        "filters": [],
        "position_sizing": {"type": "full_capital"},
        "stop": {"enabled": False},
        "target": {"enabled": False},
        "fill_timing": "next_bar_open",
        "data": {
            "source": spec.data_source,
            "legacy_costs": {
                "commission_bps": _basis_points_text(spec.commission_bps),
                "slippage_bps": _basis_points_text(spec.slippage_bps),
            },
        },
        "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
        "plugin": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


def adapt_phase1_to_v2(
    phase1_config_path: Path,
    adapter_version: str,
) -> Phase1ToV2AdapterResult:
    """Translate one supported Phase 1 YAML configuration without modifying it."""
    if not isinstance(adapter_version, str) or not adapter_version:
        raise ValueError("adapter_version must be a non-empty string")

    source_path = Path(phase1_config_path)
    source_hash = sha256_file(source_path)
    spec = load_strategy_spec(source_path)
    capability = check_capabilities(spec)
    if capability.status.value != "SUPPORTED":
        raise Phase1AdapterCapabilityBlocker(
            capability.status,
            capability.reasons,
        )

    unsupported_fields = tuple(
        field for field in _UNSUPPORTED_NULL_FIELDS if field in spec.raw
    )
    if any(spec.raw[field] is not None for field in unsupported_fields):
        raise ValueError(
            "Phase 1 adapter unsupported field(s): " + ", ".join(unsupported_fields)
        )

    generated_payload = _v2_payload(spec)
    v2_spec = validate_strategy_mapping_v2(generated_payload)
    normalized = normalize_strategy_spec(
        v2_spec,
        capability_registry=_SingleValidatedSpecRegistry(v2_spec),
        source_config_hash=source_hash,
    )
    if normalized.ir is None:
        raise ValueError("Phase 1 adapter normalization blocker: " + normalized.issues[0].message)

    source_hash_after = sha256_file(source_path)
    source_bytes_unchanged = source_hash_after == source_hash
    if not source_bytes_unchanged:
        raise RuntimeError("Phase 1 adapter source file changed during adaptation")
    warnings = (
        "Phase 1 next_bar fill is represented as V2 next_bar_open.",
        "Legacy basis-point commission and slippage are retained in data.legacy_costs.",
        *(f"{field} is null and has no V2 representation." for field in unsupported_fields),
    )
    return Phase1ToV2AdapterResult(
        source_path=source_path,
        source_hash=source_hash,
        source_hash_after=source_hash_after,
        adapter_version=adapter_version,
        v2_payload=v2_spec.payload,
        generated_v2_hash=canonical_hash(generated_payload),
        strategy_spec_v2=v2_spec,
        normalized_ir=normalized.ir,
        warnings=warnings,
        unsupported_fields=unsupported_fields,
        source_bytes_unchanged=source_bytes_unchanged,
    )


__all__ = (
    "Phase1AdapterCapabilityBlocker",
    "Phase1ToV2AdapterResult",
    "adapt_phase1_to_v2",
)
