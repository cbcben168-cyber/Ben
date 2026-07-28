"""Immutable, deterministic declarations of currently available V2.1 capabilities."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
from os import PathLike
from pathlib import Path
import re
from types import MappingProxyType

from tv_quant.run_manifest import canonical_hash

from .data_plan import _deep_freeze
from .status_codes import BlockerCode


_TOP_LEVEL_FIELDS = frozenset({"schema_version", "capabilities"})
_RECORD_FIELDS = frozenset(
    {
        "capability_id",
        "version",
        "implementation_status",
        "supported_market",
        "supported_timeframes",
        "provider",
        "required_dependencies",
        "formal_status",
        "structural_availability",
        "implementation_availability",
        "formal_eligibility",
        "smoke_only_status",
        "blocker_code",
        "evidence",
        "last_verified",
        "implementation_owner",
    }
)
_IMPLEMENTATION_STATUSES = frozenset(
    {"implemented", "not_implemented", "not_verified"}
)
_FORMAL_STATUSES = frozenset(
    {"formal_verified", "not_live_verified", "unavailable"}
)
_AVAILABILITY_STATUSES = frozenset({"available", "unavailable"})
_FORMAL_ELIGIBILITY_STATUSES = frozenset({"eligible", "not_eligible"})
_SMOKE_ONLY_STATUSES = frozenset({"smoke_only", "not_smoke_only"})
_STABLE_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]+\Z")


def _exact_fields(
    value: object, expected: frozenset[str], path: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{path}: mapping required")
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(f"{path}: exact fields required; missing={missing}; unknown={unknown}")
    return value


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: non-empty string required")
    return value


def _identifier(value: object, path: str) -> str:
    identifier = _string(value, path)
    if not _STABLE_IDENTIFIER.fullmatch(identifier):
        raise ValueError(f"{path}: stable identifier required")
    return identifier


def _string_tuple(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{path}: array of strings required")
    result = tuple(
        _string(item, f"{path}[{index}]") for index, item in enumerate(value)
    )
    return result


def _status(value: object, allowed: frozenset[str], path: str) -> str:
    status = _string(value, path)
    if status not in allowed:
        raise ValueError(f"{path}: unknown status {status!r}")
    return status


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """One fully validated capability declaration."""

    capability_id: str
    version: str
    implementation_status: str
    supported_market: tuple[str, ...]
    supported_timeframes: tuple[str, ...]
    provider: str | None
    required_dependencies: tuple[str, ...]
    formal_status: str
    structural_availability: str
    implementation_availability: str
    formal_eligibility: str
    smoke_only_status: str
    blocker_code: BlockerCode | None
    evidence: tuple[str, ...]
    last_verified: str
    implementation_owner: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "capability_id", _identifier(self.capability_id, "capability_id")
        )
        object.__setattr__(self, "version", _identifier(self.version, "version"))
        object.__setattr__(
            self,
            "implementation_status",
            _status(
                self.implementation_status,
                _IMPLEMENTATION_STATUSES,
                "implementation_status",
            ),
        )
        object.__setattr__(
            self,
            "supported_market",
            _string_tuple(self.supported_market, "supported_market"),
        )
        object.__setattr__(
            self,
            "supported_timeframes",
            _string_tuple(self.supported_timeframes, "supported_timeframes"),
        )
        if self.provider is not None:
            object.__setattr__(self, "provider", _identifier(self.provider, "provider"))
        object.__setattr__(
            self,
            "required_dependencies",
            _string_tuple(self.required_dependencies, "required_dependencies"),
        )
        object.__setattr__(
            self,
            "formal_status",
            _status(self.formal_status, _FORMAL_STATUSES, "formal_status"),
        )
        object.__setattr__(
            self,
            "structural_availability",
            _status(
                self.structural_availability,
                _AVAILABILITY_STATUSES,
                "structural_availability",
            ),
        )
        object.__setattr__(
            self,
            "implementation_availability",
            _status(
                self.implementation_availability,
                _AVAILABILITY_STATUSES,
                "implementation_availability",
            ),
        )
        object.__setattr__(
            self,
            "formal_eligibility",
            _status(
                self.formal_eligibility,
                _FORMAL_ELIGIBILITY_STATUSES,
                "formal_eligibility",
            ),
        )
        object.__setattr__(
            self,
            "smoke_only_status",
            _status(
                self.smoke_only_status,
                _SMOKE_ONLY_STATUSES,
                "smoke_only_status",
            ),
        )
        if self.blocker_code is not None and not isinstance(
            self.blocker_code, BlockerCode
        ):
            try:
                object.__setattr__(self, "blocker_code", BlockerCode(self.blocker_code))
            except (TypeError, ValueError) as exc:
                raise ValueError("blocker_code: unknown blocker code") from exc
        object.__setattr__(self, "evidence", _string_tuple(self.evidence, "evidence"))
        object.__setattr__(
            self, "last_verified", _string(self.last_verified, "last_verified")
        )
        object.__setattr__(
            self,
            "implementation_owner",
            _identifier(self.implementation_owner, "implementation_owner"),
        )
        self._validate_consistency()

    def _validate_consistency(self) -> None:
        if self.formal_status == "formal_verified" and self.blocker_code is not None:
            raise ValueError("formal record cannot carry blocker_code")
        if self.smoke_only_status == "smoke_only" and self.formal_eligibility == "eligible":
            raise ValueError("smoke-only capability cannot be formal-eligible")
        if self.formal_eligibility == "eligible":
            if self.implementation_status != "implemented":
                raise ValueError("formal capability must be implemented")
            if self.structural_availability != "available":
                raise ValueError("formal capability must be structurally available")
            if self.implementation_availability != "available":
                raise ValueError("formal capability implementation must be available")
            if self.formal_status != "formal_verified":
                raise ValueError("formal capability must be formal_verified")
            if self.smoke_only_status != "not_smoke_only":
                raise ValueError("formal capability cannot be smoke-only")
        elif self.formal_status == "formal_verified":
            raise ValueError("formal_verified capability must be formal-eligible")
        if (
            self.implementation_status != "implemented"
            and self.implementation_availability == "available"
        ):
            raise ValueError("available implementation must be implemented")
        if self.formal_status == "unavailable" and self.blocker_code is None:
            raise ValueError("unavailable capability requires blocker_code")


@dataclass(frozen=True, slots=True, init=False)
class CapabilityRegistry:
    """A validated capability registry with deterministic lookup and snapshots."""

    schema_version: str
    capabilities: tuple[CapabilityRecord, ...]
    _records: Mapping[tuple[str, str], CapabilityRecord]

    def __init__(self, payload: object) -> None:
        root = _exact_fields(payload, _TOP_LEVEL_FIELDS, "registry")
        schema_version = _string(root["schema_version"], "schema_version")
        if schema_version != "v2.1":
            raise ValueError("schema_version: must equal v2.1")
        raw_capabilities = root["capabilities"]
        if not isinstance(raw_capabilities, (list, tuple)) or not raw_capabilities:
            raise ValueError("capabilities: non-empty array required")

        records: list[CapabilityRecord] = []
        seen_ids: set[str] = set()
        for index, raw_record in enumerate(raw_capabilities):
            record_mapping = _exact_fields(
                raw_record, _RECORD_FIELDS, f"capabilities[{index}] record"
            )
            record = CapabilityRecord(**dict(record_mapping))
            if record.capability_id in seen_ids:
                raise ValueError(
                    f"duplicate capability ID: {record.capability_id!r}"
                )
            seen_ids.add(record.capability_id)
            records.append(record)

        ordered = tuple(
            sorted(records, key=lambda item: (item.capability_id, item.version))
        )
        object.__setattr__(self, "schema_version", schema_version)
        object.__setattr__(self, "capabilities", ordered)
        object.__setattr__(
            self,
            "_records",
            MappingProxyType(
                {(record.capability_id, record.version): record for record in ordered}
            ),
        )

    def get(self, capability_id: str, version: str) -> CapabilityRecord | None:
        return self._records.get((capability_id, version))

    def require(self, capability_id: str, version: str) -> CapabilityRecord:
        record = self.get(capability_id, version)
        if record is None:
            raise ValueError(
                f"capability not registered: {capability_id!r} version {version!r}"
            )
        return record

    def require_formal(self, capability_id: str, version: str) -> CapabilityRecord:
        record = self.require(capability_id, version)
        if (
            record.structural_availability != "available"
            or record.implementation_availability != "available"
            or record.formal_eligibility != "eligible"
            or record.formal_status != "formal_verified"
            or record.smoke_only_status != "not_smoke_only"
        ):
            raise ValueError(
                f"capability is not formal-eligible: {capability_id!r} version {version!r}"
            )
        return record

    def snapshot_payload(self) -> Mapping[str, object]:
        records = [
            {
                "capability_id": record.capability_id,
                "version": record.version,
                "implementation_status": record.implementation_status,
                "supported_market": record.supported_market,
                "supported_timeframes": record.supported_timeframes,
                "provider": record.provider,
                "required_dependencies": record.required_dependencies,
                "formal_status": record.formal_status,
                "structural_availability": record.structural_availability,
                "implementation_availability": record.implementation_availability,
                "formal_eligibility": record.formal_eligibility,
                "smoke_only_status": record.smoke_only_status,
                "blocker_code": (
                    record.blocker_code.value
                    if record.blocker_code is not None
                    else None
                ),
                "evidence": record.evidence,
                "implementation_owner": record.implementation_owner,
            }
            for record in self.capabilities
        ]
        frozen = _deep_freeze(
            {"schema_version": self.schema_version, "capabilities": records},
            "capability_snapshot",
        )
        if not isinstance(frozen, Mapping):
            raise ValueError("capability_snapshot: object required")
        return frozen

    def snapshot_hash(self) -> str:
        return capability_snapshot_hash(self)


def _reject_duplicate_json_fields(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key!r}")
        result[key] = value
    return result


def load_capability_registry(
    path: str | PathLike[str],
) -> CapabilityRegistry:
    """Load and fully validate one local versioned JSON registry."""
    try:
        payload = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_json_fields,
        )
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid capability registry JSON: {exc.msg}") from exc
    return CapabilityRegistry(payload)


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(value[key]) for key in value}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def capability_snapshot_hash(registry: CapabilityRegistry) -> str:
    """Hash only a validated deterministic snapshot through the canonical owner."""
    if not isinstance(registry, CapabilityRegistry):
        raise ValueError("CapabilityRegistry required")
    payload = _thaw(registry.snapshot_payload())
    if not isinstance(payload, Mapping):
        raise ValueError("capability snapshot mapping required")
    return canonical_hash(payload)


__all__ = (
    "CapabilityRecord",
    "CapabilityRegistry",
    "capability_snapshot_hash",
    "load_capability_registry",
)
