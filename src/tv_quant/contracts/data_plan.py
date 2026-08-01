"""Declarative V2.1 data requirements; this module never accesses market data."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from tv_quant.run_manifest import canonical_hash

from .ast_contract import PredicateExpression, ValueExpression
from .normalized_ir import NormalizedStrategyIR


_PROVIDER_PREFERENCE = (
    "validated_local_cache_first",
    "futu_opend_incremental",
    "validated_csv_parquet_import",
    "yfinance_smoke_only",
)
_PRIMARY_CAPABILITIES = ("daily_ohlcv_utc", "STRUCTURAL_ONLY")


@dataclass(frozen=True, slots=True)
class DatasetRequirement:
    """One dataset declaration, not a handle to data or a provider."""

    dataset_role: str
    provider_preference: tuple[str, ...]
    symbol: str
    market: str
    timeframe: str
    session: Mapping[str, object]
    timezone: str
    requested_start: str
    requested_end: str
    warmup_bars: int
    adjustment_requirement: str
    corporate_action_requirement: str
    cost_profile_requirement: str
    capability_requirements: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", _frozen_mapping(self.session, "session"))
        object.__setattr__(self, "provider_preference", tuple(self.provider_preference))
        object.__setattr__(self, "capability_requirements", tuple(self.capability_requirements))


@dataclass(frozen=True, slots=True)
class DataPlan:
    """Immutable declarations needed before a future data adapter may run."""

    schema_version: str
    primary: DatasetRequirement
    auxiliary: tuple[DatasetRequirement, ...]
    requested_range: Mapping[str, object]
    data_plan_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "auxiliary", tuple(self.auxiliary))
        object.__setattr__(
            self, "requested_range", _frozen_mapping(self.requested_range, "requested_range")
        )


def _frozen_mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{path}: object required")
    return MappingProxyType(
        {key: _deep_freeze(value[key], f"{path}.{key}") for key in sorted(value)}
    )


def _deep_freeze(value: object, path: str) -> object:
    if isinstance(value, Mapping):
        return _frozen_mapping(value, path)
    if isinstance(value, (list, tuple)):
        return tuple(_deep_freeze(item, f"{path}[{index}]") for index, item in enumerate(value))
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    raise ValueError(f"{path}: immutable JSON-like value required")


def _periods(value: object) -> tuple[int, ...]:
    if isinstance(value, ValueExpression):
        parameters = value.payload.get("parameters")
        if isinstance(parameters, Mapping):
            period = parameters.get("period")
            if isinstance(period, int) and not isinstance(period, bool):
                return (period,)
        return ()
    if isinstance(value, PredicateExpression):
        return _periods(value.payload)
    if isinstance(value, Mapping):
        return tuple(period for item in value.values() for period in _periods(item))
    if isinstance(value, tuple):
        return tuple(period for item in value for period in _periods(item))
    return ()


def _warmup_bars(ir: NormalizedStrategyIR) -> int:
    periods = _periods((ir.entry, ir.exit, ir.filters))
    return max(periods, default=0)


def _require_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: non-empty string required")
    return value


def _primary_requirement(ir: NormalizedStrategyIR) -> DatasetRequirement:
    data = _frozen_mapping(ir.data, "ir.data")
    range_ = _frozen_mapping(ir.backtest_range, "ir.backtest_range")
    return DatasetRequirement(
        dataset_role="primary",
        provider_preference=_PROVIDER_PREFERENCE,
        symbol=ir.symbol,
        market=ir.market,
        timeframe=ir.timeframe,
        session=_frozen_mapping(ir.session, "ir.session"),
        timezone="UTC",
        requested_start=_require_string(range_.get("start"), "ir.backtest_range.start"),
        requested_end=_require_string(range_.get("end"), "ir.backtest_range.end"),
        warmup_bars=_warmup_bars(ir),
        adjustment_requirement=_require_string(
            data.get("adjustment_requirement", "adjusted_ohlcv"), "ir.data.adjustment_requirement"
        ),
        corporate_action_requirement=_require_string(
            data.get("corporate_action_requirement", "corporate_actions_required"),
            "ir.data.corporate_action_requirement",
        ),
        cost_profile_requirement=_require_string(
            data.get("cost_profile", "cost_profile_required"), "ir.data.cost_profile"
        ),
        capability_requirements=_PRIMARY_CAPABILITIES,
    )


def _auxiliary_requirements(
    ir: NormalizedStrategyIR,
    primary: DatasetRequirement,
    capability_registry: object,
) -> tuple[DatasetRequirement, ...]:
    auxiliary = ir.data.get("auxiliary", ())
    if auxiliary in (None, ()):
        return ()
    if not isinstance(auxiliary, tuple):
        raise ValueError("ir.data.auxiliary: array required")
    requirements: list[DatasetRequirement] = []
    for index, raw in enumerate(auxiliary):
        item = _frozen_mapping(raw, f"ir.data.auxiliary[{index}]")
        role = _require_string(item.get("dataset_role"), f"ir.data.auxiliary[{index}].dataset_role")
        capability_id = _require_string(
            item.get("capability_id", f"auxiliary.{role}"),
            f"ir.data.auxiliary[{index}].capability_id",
        )
        capability_version = _require_string(
            item.get("capability_version", "v2.1"),
            f"ir.data.auxiliary[{index}].capability_version",
        )
        lookup = getattr(capability_registry, "get", None)
        if not callable(lookup):
            raise ValueError("capability_registry.get required for auxiliary datasets")
        record = lookup(capability_id, capability_version)
        blocker = "FILTER_DATA_CAPABILITY_BLOCKER"
        if record is not None:
            record_blocker = getattr(record, "blocker_code", None)
            if record_blocker is not None:
                blocker = getattr(record_blocker, "value", record_blocker)
            elif (
                getattr(record, "implementation_availability", None) == "available"
                and getattr(record, "formal_eligibility", None) == "eligible"
            ):
                blocker = "AVAILABLE"
        capability_status = (
            "AVAILABLE" if blocker == "AVAILABLE" else f"BLOCKED:{blocker}"
        )
        requirements.append(
            DatasetRequirement(
                dataset_role=role,
                provider_preference=_PROVIDER_PREFERENCE,
                symbol=_require_string(item.get("symbol"), f"ir.data.auxiliary[{index}].symbol"),
                market=_require_string(item.get("market", ir.market), f"ir.data.auxiliary[{index}].market"),
                timeframe=_require_string(item.get("timeframe", ir.timeframe), f"ir.data.auxiliary[{index}].timeframe"),
                session=primary.session,
                timezone="UTC",
                requested_start=primary.requested_start,
                requested_end=primary.requested_end,
                warmup_bars=primary.warmup_bars,
                adjustment_requirement=primary.adjustment_requirement,
                corporate_action_requirement=primary.corporate_action_requirement,
                cost_profile_requirement=primary.cost_profile_requirement,
                capability_requirements=(
                    f"{capability_id}@{capability_version}",
                    capability_status,
                ),
            )
        )
    return tuple(requirements)


def _dataset_payload(requirement: DatasetRequirement) -> dict[str, object]:
    return {
        field: getattr(requirement, field)
        for field in DatasetRequirement.__dataclass_fields__
    }


def _payload(plan: DataPlan) -> dict[str, object]:
    return {
        "schema_version": plan.schema_version,
        "primary": _dataset_payload(plan.primary),
        "auxiliary": [_dataset_payload(requirement) for requirement in plan.auxiliary],
        "requested_range": dict(plan.requested_range),
    }


def data_plan_hash(plan: DataPlan) -> str:
    """Hash a DataPlan through the existing manifest hash owner."""
    if not isinstance(plan, DataPlan):
        raise ValueError("DataPlan required")
    return canonical_hash(_payload(plan))


def build_data_plan(ir: NormalizedStrategyIR, capability_registry: object) -> DataPlan:
    """Build declarations only; provider and registry execution are deliberately absent."""
    if not isinstance(ir, NormalizedStrategyIR):
        raise ValueError("NormalizedStrategyIR required")
    _ = capability_registry
    primary = _primary_requirement(ir)
    plan = DataPlan(
        schema_version=ir.schema_version,
        primary=primary,
        auxiliary=_auxiliary_requirements(ir, primary, capability_registry),
        requested_range=_frozen_mapping(ir.backtest_range, "ir.backtest_range"),
        data_plan_hash="",
    )
    return DataPlan(
        schema_version=plan.schema_version,
        primary=plan.primary,
        auxiliary=plan.auxiliary,
        requested_range=plan.requested_range,
        data_plan_hash=data_plan_hash(plan),
    )


__all__ = ("DataPlan", "DatasetRequirement", "build_data_plan", "data_plan_hash")
