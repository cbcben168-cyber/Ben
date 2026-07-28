"""Formal immutable execution assumptions for the V2.1 confirmation boundary."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
import re
from types import MappingProxyType

from tv_quant.run_manifest import canonical_hash

from .data_plan import DataPlan
from .normalized_ir import NormalizedStrategyIR
from .numeric import canonical_integer


_CALLER_FIELDS = frozenset(
    {
        "cost_profile_id",
        "corporate_action_profile_id",
        "benchmark_protocol_id",
        "benchmark_protocol_version",
        "capability_snapshot_hash",
        "normalizer_version",
    }
)
_SESSION_FIELDS = frozenset({"timezone", "regular_hours_only", "calendar_id"})
_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_STABLE_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]+\Z")
_DISALLOWED_IDENTIFIER_SEGMENTS = frozenset(
    {"lambda", "eval", "exec", "compile", "__import__", "importlib"}
)


def _frozen_value(value: object, path: str) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(f"{path}: object keys must be strings")
        return MappingProxyType(
            {key: _frozen_value(value[key], f"{path}.{key}") for key in sorted(value)}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_frozen_value(item, f"{path}[{index}]") for index, item in enumerate(value))
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, (float, Decimal)):
        raise ValueError(f"{path}: non-canonical numeric value is not permitted")
    raise ValueError(f"{path}: immutable JSON-like value required")


def _non_empty_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: non-empty string required")
    return value


def _stable_identifier(value: object, path: str) -> str:
    identifier = _non_empty_string(value, path)
    normalized_identifier = identifier.lower()
    segments = re.split(r"[._:-]", identifier)
    if (
        not _STABLE_IDENTIFIER.fullmatch(identifier)
        or normalized_identifier in _DISALLOWED_IDENTIFIER_SEGMENTS
        or any(segment.lower() in _DISALLOWED_IDENTIFIER_SEGMENTS for segment in segments)
    ):
        raise ValueError(f"{path}: stable identifier required")
    return identifier


def _capability_snapshot_hash(value: object, path: str) -> str:
    snapshot_hash = _non_empty_string(value, path)
    if not _SHA256_HEX.fullmatch(snapshot_hash):
        raise ValueError(f"{path}: lowercase SHA-256 hex required")
    return snapshot_hash


@dataclass(frozen=True, slots=True)
class ExecutionAssumptions:
    """All V2.1 execution semantics that must bind a confirmation."""

    initial_capital_policy: str
    fill_timing: str
    session_policy: Mapping[str, object]
    optimization_policy: str
    report_language: str
    cost_profile_id: str
    corporate_action_profile_id: str
    benchmark_protocol_id: str
    capability_snapshot_hash: str
    schema_version: str
    compiler_version: str
    normalizer_version: str
    benchmark_protocol_version: str
    engine_status: str
    plugin: None

    def __post_init__(self) -> None:
        for field in (
            "initial_capital_policy",
            "fill_timing",
            "optimization_policy",
            "report_language",
            "cost_profile_id",
            "corporate_action_profile_id",
            "benchmark_protocol_id",
            "capability_snapshot_hash",
            "schema_version",
            "compiler_version",
            "normalizer_version",
            "benchmark_protocol_version",
            "engine_status",
        ):
            _non_empty_string(getattr(self, field), field)
        if self.plugin is not None:
            raise ValueError("plugin: V2.1 requires null")
        for field in (
            "cost_profile_id",
            "corporate_action_profile_id",
            "benchmark_protocol_id",
            "benchmark_protocol_version",
            "normalizer_version",
        ):
            _stable_identifier(getattr(self, field), field)
        _capability_snapshot_hash(self.capability_snapshot_hash, "capability_snapshot_hash")
        session_policy = _frozen_value(self.session_policy, "session_policy")
        if not isinstance(session_policy, Mapping):
            raise ValueError("session_policy: object required")
        if set(session_policy) != _SESSION_FIELDS:
            raise ValueError("session_policy: exact keys required")
        object.__setattr__(self, "session_policy", session_policy)
        _non_empty_string(session_policy.get("timezone"), "session_policy.timezone")
        if not isinstance(session_policy.get("regular_hours_only"), bool):
            raise ValueError("session_policy.regular_hours_only: boolean required")
        _non_empty_string(session_policy.get("calendar_id"), "session_policy.calendar_id")
        if self.fill_timing != "next_bar_open":
            raise ValueError("fill_timing: must equal next_bar_open")
        if session_policy.get("timezone") != "America/New_York":
            raise ValueError("session_policy.timezone: must equal America/New_York")
        if session_policy.get("regular_hours_only") is not True:
            raise ValueError("session_policy.regular_hours_only: must equal true")
        if self.initial_capital_policy != "100000 USD":
            raise ValueError("initial_capital_policy: must equal 100000 USD")
        if self.optimization_policy != "false":
            raise ValueError("optimization_policy: must equal false")
        if self.report_language != "zh-CN":
            raise ValueError("report_language: must equal zh-CN")
        if self.engine_status != "NOT_IMPLEMENTED":
            raise ValueError("engine_status: must equal NOT_IMPLEMENTED")
        if (
            self.schema_version != "v2.1"
            or self.compiler_version != "v2.1"
            or self.normalizer_version != "v2.1"
        ):
            raise ValueError("schema/compiler/normalizer version: must equal v2.1")


def _caller_inputs(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise ValueError("capability_registry: mapping required")
    if set(value) != _CALLER_FIELDS:
        raise ValueError("capability_registry: exact caller metadata keys required")
    caller = {
        key: (
            _capability_snapshot_hash(value[key], f"capability_registry.{key}")
            if key == "capability_snapshot_hash"
            else _stable_identifier(value[key], f"capability_registry.{key}")
        )
        for key in sorted(_CALLER_FIELDS)
    }
    if caller["normalizer_version"] != "v2.1":
        raise ValueError("capability_registry.normalizer_version: must equal v2.1")
    return MappingProxyType(caller)


def _validated_session(value: object) -> Mapping[str, object]:
    session = _frozen_value(value, "ir.session")
    if not isinstance(session, Mapping):  # defensive: _frozen_value preserves mapping type
        raise ValueError("ir.session: object required")
    if set(session) != _SESSION_FIELDS:
        raise ValueError("ir.session: exact keys required")
    if session.get("timezone") != "America/New_York":
        raise ValueError("ir.session.timezone: must equal America/New_York")
    if session.get("regular_hours_only") is not True:
        raise ValueError("ir.session.regular_hours_only: must equal true")
    _non_empty_string(session.get("calendar_id"), "ir.session.calendar_id")
    return session


def build_execution_assumptions(
    ir: NormalizedStrategyIR,
    data_plan: DataPlan,
    capability_registry: object,
) -> ExecutionAssumptions:
    """Build assumptions from validated declarations and explicit caller metadata only."""
    if not isinstance(ir, NormalizedStrategyIR):
        raise ValueError("NormalizedStrategyIR required")
    if not isinstance(data_plan, DataPlan):
        raise ValueError("DataPlan required")
    caller = _caller_inputs(capability_registry)
    if ir.schema_version != "v2.1" or data_plan.schema_version != ir.schema_version:
        raise ValueError("schema_version: matching v2.1 declarations required")
    if ir.compiler_version != "v2.1":
        raise ValueError("compiler_version: must equal v2.1")
    if canonical_integer(ir.initial_capital.get("amount"), "ir.initial_capital.amount") != 100000:
        raise ValueError("initial_capital: must equal integer 100000 USD")
    if ir.initial_capital.get("currency") != "USD":
        raise ValueError("initial_capital: must equal integer 100000 USD")
    if ir.fill_timing != "next_bar_open":
        raise ValueError("fill_timing: must equal next_bar_open")
    if ir.optimization_allowed is not False:
        raise ValueError("optimization_allowed: must equal false")
    if ir.report_language != "zh-CN":
        raise ValueError("report_language: must equal zh-CN")
    if ir.plugin is not None:
        raise ValueError("plugin: V2.1 plugin execution is not implemented")

    return ExecutionAssumptions(
        initial_capital_policy="100000 USD",
        fill_timing=ir.fill_timing,
        session_policy=_validated_session(ir.session),
        optimization_policy="false",
        report_language=ir.report_language,
        cost_profile_id=caller["cost_profile_id"],
        corporate_action_profile_id=caller["corporate_action_profile_id"],
        benchmark_protocol_id=caller["benchmark_protocol_id"],
        capability_snapshot_hash=caller["capability_snapshot_hash"],
        schema_version=ir.schema_version,
        compiler_version=ir.compiler_version,
        normalizer_version=caller["normalizer_version"],
        benchmark_protocol_version=caller["benchmark_protocol_version"],
        engine_status="NOT_IMPLEMENTED",
        plugin=None,
    )


def _payload_value(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _payload_value(value[key]) for key in sorted(value)})
    if isinstance(value, tuple):
        return tuple(_payload_value(item) for item in value)
    if isinstance(value, (float, Decimal)) or callable(value):
        raise ValueError("assumptions contain forbidden non-canonical value")
    return value


def execution_assumptions_payload(assumptions: ExecutionAssumptions) -> Mapping[str, object]:
    """Return a fresh deterministic JSON-like payload for the hash owner."""
    if not isinstance(assumptions, ExecutionAssumptions):
        raise ValueError("ExecutionAssumptions required")
    return MappingProxyType({
        field: _payload_value(getattr(assumptions, field))
        for field in ExecutionAssumptions.__dataclass_fields__
    })


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(value[key]) for key in value}
    if isinstance(value, tuple):
        return tuple(_thaw(item) for item in value)
    return value


def assumptions_hash(assumptions: ExecutionAssumptions) -> str:
    """Hash only the typed canonical assumptions through the manifest hash owner."""
    if not isinstance(assumptions, ExecutionAssumptions):
        raise ValueError("ExecutionAssumptions required")
    return canonical_hash(_thaw(execution_assumptions_payload(assumptions)))


__all__ = (
    "ExecutionAssumptions",
    "assumptions_hash",
    "build_execution_assumptions",
    "execution_assumptions_payload",
)
