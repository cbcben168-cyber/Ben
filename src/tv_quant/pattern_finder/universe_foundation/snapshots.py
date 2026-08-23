"""Deterministic immutable snapshots of existing Task 10/6/8 results."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
import json
import os
from pathlib import Path
import re
import tempfile
from types import MappingProxyType
from typing import Any
from uuid import UUID

from tv_quant.run_manifest import canonical_hash

from .evaluator import (
    FieldDecision,
    NormalizedPrerequisiteDecision,
    SecurityEvaluation,
    SecurityEvaluationPrerequisites,
)
from .evidence import (
    AttemptStatus,
    Completeness,
    Decision,
    EvidenceReference,
    RawIndustryEvidence,
    RawPlateEvidence,
    SecurityClassificationEvidence,
    evidence_record_sha256,
)
from .funnel import FunnelStage, UniverseFunnel, funnel_sha256
from .futu_adapter import RawApiBatch
from .futu_gateway import (
    ApiBatchRecord,
    GatewayAttempt,
    IdentityLedgerEntry,
    prerequisites_sha256,
)
from .profiles import RecordState, UniverseDraft, UniverseProfile


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA_VERSION = "universe-snapshot/v1"
_CODEC_TYPE = "__snapshot_codec_type__"
_CODEC_ITEMS = "items"
_AUDIT_NAME = "name"

_FUNNEL_STAGE_IDS = (
    "S0_DISCOVERED_US_CASH_SECURITIES",
    "S1_IDENTITY_VALID",
    "S2_EXCHANGE_ALLOWED",
    "S3_SECURITY_CLASS_ALLOWED",
    "S4_ACTIVE_STATUS_ALLOWED",
    "S5_PRICE_ALLOWED",
    "S6_MARKET_CAP_ALLOWED",
    "S7_SECTOR_INDUSTRY_ALLOWED",
    "S8_LISTING_HISTORY_ALLOWED",
    "S9_LIQUIDITY_ALLOWED",
    "S10_CORE_UNIVERSE",
)


class SnapshotValidationError(ValueError):
    """A snapshot violates its immutable producer binding."""


class SnapshotStoreError(OSError):
    """Snapshot persistence failed."""


class SnapshotConflictError(SnapshotStoreError):
    """An immutable snapshot ID already binds different content."""


class SnapshotNotFoundError(SnapshotStoreError):
    """The requested snapshot ID is absent."""


class SnapshotCorruptError(SnapshotStoreError):
    """Persisted snapshot bytes are malformed or fail validation."""


class SnapshotKind(str, Enum):
    FORMAL = "FORMAL"
    PREVIEW = "PREVIEW"


@dataclass(frozen=True, slots=True, eq=False)
class _FrozenAuditList(Sequence[object]):
    """Logical list whose snapshot-owned contents cannot be mutated."""

    _items: tuple[object, ...]

    def __getitem__(self, index: int | slice) -> object:
        return self._items[index]

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._items)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Sequence) and not isinstance(
            other, (str, bytes, bytearray)
        ) and tuple(self) == tuple(other)

    def __hash__(self) -> int:
        return hash(self._items)


def _freeze_audit(value: object) -> object:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) in (float, Decimal, UUID, datetime, date, Decision, EvidenceReference):
        if type(value) is float and (
            value != value or value in (float("inf"), float("-inf"))
        ):
            raise SnapshotValidationError("audit float: finite value required")
        if type(value) is Decimal and not value.is_finite():
            raise SnapshotValidationError("audit Decimal: finite value required")
        if type(value) is datetime:
            _utc(value, "audit datetime")
        return value
    if type(value) is _FrozenAuditList:
        return value
    if type(value) is list:
        return _FrozenAuditList(tuple(_freeze_audit(item) for item in value))
    if type(value) is tuple:
        return tuple(_freeze_audit(item) for item in value)
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise SnapshotValidationError("audit mapping: string keys required")
        return MappingProxyType(
            {key: _freeze_audit(item) for key, item in sorted(value.items())}
        )
    if isinstance(value, Enum) or (is_dataclass(value) and not isinstance(value, type)):
        raise SnapshotValidationError(
            f"unsupported audit type: {type(value).__name__}"
        )
    raise SnapshotValidationError(f"unsupported audit type: {type(value).__name__}")


def _audit_canonical(value: object) -> object:
    value = _freeze_audit(value)
    if type(value) is Decision:
        return {_CODEC_TYPE: "audit-enum", _AUDIT_NAME: "Decision", "value": value.value}
    if type(value) is EvidenceReference:
        return {
            _CODEC_TYPE: "audit-dataclass",
            _AUDIT_NAME: "EvidenceReference",
            "fields": {
                "source_id": value.source_id,
                "source_locator": value.source_locator,
                "source_record_sha256": value.source_record_sha256,
            },
        }
    if type(value) is _FrozenAuditList:
        return {
            _CODEC_TYPE: "list",
            _CODEC_ITEMS: [_audit_canonical(item) for item in value],
        }
    if type(value) is tuple:
        return {
            _CODEC_TYPE: "tuple",
            _CODEC_ITEMS: [_audit_canonical(item) for item in value],
        }
    if isinstance(value, Mapping):
        return {
            _CODEC_TYPE: "mapping",
            _CODEC_ITEMS: [
                [key, _audit_canonical(item)] for key, item in sorted(value.items())
            ],
        }
    return _canonical(value)


def _freeze_field_decision(value: FieldDecision) -> FieldDecision:
    if type(value) is not FieldDecision:
        raise SnapshotValidationError("field_decision: FieldDecision required")
    return FieldDecision(
        field_id=value.field_id,
        raw_value=_freeze_audit(value.raw_value),
        normalized_value=_freeze_audit(value.normalized_value),
        operator=value.operator,
        threshold=_freeze_audit(value.threshold),
        decision=value.decision,
        reason_code=value.reason_code,
        evidence_source=value.evidence_source,
        evidence_observed_at_utc=value.evidence_observed_at_utc,
        evidence_version=value.evidence_version,
        evidence_references=value.evidence_references,
    )


def _non_empty(value: object, field_id: str) -> str:
    if type(value) is not str or not value.strip():
        raise SnapshotValidationError(f"{field_id}: non-empty string required")
    return value


def _optional_string(value: object, field_id: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise SnapshotValidationError(f"{field_id}: string or None required")
    return value


def _hash(value: object, field_id: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise SnapshotValidationError(f"{field_id}: lowercase SHA-256 required")
    return value


def _utc(value: object, field_id: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise SnapshotValidationError(f"{field_id}: UTC datetime required")
    return value


def _reference_key(reference: EvidenceReference) -> tuple[str, str, str]:
    return (
        reference.source_id,
        reference.source_locator,
        reference.source_record_sha256,
    )


def _references(
    values: Sequence[EvidenceReference], field_id: str
) -> tuple[EvidenceReference, ...]:
    result = tuple(values)
    if any(type(item) is not EvidenceReference for item in result):
        raise SnapshotValidationError(
            f"{field_id}: EvidenceReference values required"
        )
    return tuple(sorted(result, key=_reference_key))


def _canonical(value: object) -> object:
    """Convert typed immutable values to canonical-JSON values for shared hashing."""

    if type(value) is FieldDecision:
        return {
            field.name: (
                _audit_canonical(getattr(value, field.name))
                if field.name in {"raw_value", "normalized_value", "threshold"}
                else _canonical(getattr(value, field.name))
            )
            for field in fields(value)
        }
    if type(value) is _FrozenAuditList:
        return {
            _CODEC_TYPE: "list",
            _CODEC_ITEMS: [_canonical(item) for item in value],
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, UUID):
        return {"__uuid__": str(value)}
    if isinstance(value, datetime):
        return {"__datetime__": _utc(value, "datetime").isoformat()}
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise SnapshotValidationError("Decimal: finite value required")
        return {"__decimal__": format(value, "f")}
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise SnapshotValidationError("float: finite value required")
        return {"__float__": repr(value)}
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise SnapshotValidationError("mapping: string keys required")
        return {
            _CODEC_TYPE: "mapping",
            _CODEC_ITEMS: [
                [key, _canonical(item)] for key, item in sorted(value.items())
            ],
        }
    if isinstance(value, tuple):
        return {
            _CODEC_TYPE: "tuple",
            _CODEC_ITEMS: [_canonical(item) for item in value],
        }
    if isinstance(value, list):
        return {
            _CODEC_TYPE: "list",
            _CODEC_ITEMS: [_canonical(item) for item in value],
        }
    if value is None or type(value) in (bool, int, str):
        return value
    raise SnapshotValidationError(
        f"canonical snapshot value unsupported: {type(value).__name__}"
    )


def _decode_audit(value: object) -> object:
    if isinstance(value, list):
        return [_decode_audit(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {_CODEC_TYPE, _AUDIT_NAME, "value"}:
            if value[_CODEC_TYPE] != "audit-enum" or value[_AUDIT_NAME] != "Decision":
                raise SnapshotValidationError("codec: unsupported audit enum")
            return Decision(str(value["value"]))
        if set(value) == {_CODEC_TYPE, _AUDIT_NAME, "fields"}:
            if (
                value[_CODEC_TYPE] != "audit-dataclass"
                or value[_AUDIT_NAME] != "EvidenceReference"
                or not isinstance(value["fields"], Mapping)
            ):
                raise SnapshotValidationError("codec: unsupported audit dataclass")
            return _reference_from(value["fields"])
        if set(value) == {_CODEC_TYPE, _CODEC_ITEMS}:
            kind = value[_CODEC_TYPE]
            items = value[_CODEC_ITEMS]
            if type(kind) is not str or not isinstance(items, list):
                raise SnapshotValidationError("codec: valid kind/items required")
            if kind == "mapping":
                result: dict[str, object] = {}
                for pair in items:
                    if (
                        not isinstance(pair, list)
                        or len(pair) != 2
                        or type(pair[0]) is not str
                        or pair[0] in result
                    ):
                        raise SnapshotValidationError(
                            "codec mapping: unique string-key pairs required"
                        )
                    result[pair[0]] = _decode_audit(pair[1])
                return MappingProxyType(result)
            decoded = [_decode_audit(item) for item in items]
            if kind == "tuple":
                return tuple(decoded)
            if kind == "list":
                return _FrozenAuditList(tuple(decoded))
            raise SnapshotValidationError("codec: unknown collection kind")
        if set(value) == {"__uuid__"}:
            return UUID(str(value["__uuid__"]))
        if set(value) == {"__datetime__"}:
            return datetime.fromisoformat(str(value["__datetime__"]))
        if set(value) == {"__date__"}:
            return date.fromisoformat(str(value["__date__"]))
        if set(value) == {"__decimal__"}:
            try:
                return Decimal(str(value["__decimal__"]))
            except InvalidOperation as error:
                raise SnapshotValidationError("codec: invalid Decimal") from error
        if set(value) == {"__float__"}:
            return float(str(value["__float__"]))
        return MappingProxyType(
            {str(key): _decode_audit(item) for key, item in value.items()}
        )
    return value


def _tuple_from(value: object, field_id: str) -> tuple[object, ...]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {_CODEC_TYPE, _CODEC_ITEMS}
        or value[_CODEC_TYPE] != "tuple"
        or not isinstance(value[_CODEC_ITEMS], list)
    ):
        raise SnapshotValidationError(f"{field_id}: encoded tuple required")
    return tuple(value[_CODEC_ITEMS])


@dataclass(frozen=True, slots=True)
class UniverseSnapshotHeader:
    universe_snapshot_id: UUID
    snapshot_schema_version: str
    snapshot_kind: SnapshotKind
    completeness: Completeness
    profile_version_id: str | None
    profile_content_sha256: str | None
    draft_id: str | None
    draft_content_sha256: str | None
    as_of_session: date
    created_at_utc: datetime
    gateway_attempt_id: str
    gateway_attempt_observed_at_utc: datetime
    provider_update_time: datetime | None
    gateway_attempt_status: AttemptStatus
    gateway_preflight_as_of_session: date
    gateway_preflight_observed_at_utc: datetime
    gateway_preflight_provider_update_time: datetime | None
    gateway_preflight_market_data_delay_class: str
    gateway_preflight_formal_ready: bool
    gateway_preflight_reason_codes: tuple[str, ...]
    gateway_runtime_evidence_window_seconds: float
    gateway_attempt_reason_codes: tuple[str, ...]
    gateway_attempt_sha256: str
    provider: str
    provider_sdk_version: str
    opend_server_version: str
    gateway_batches: tuple[ApiBatchRecord, ...]
    gateway_identity_ledger: tuple[IdentityLedgerEntry, ...]
    market_data_delay_evidence: tuple[ApiBatchRecord, ...]
    realtime_capability_probes: tuple[RawApiBatch, ...]
    market_data_delay_class: str
    market_state_consistency_sha256: str
    active_status_mapping_provider: str
    active_status_mapping_provider_sdk_version: str
    active_status_mapping_opend_server_version: str
    active_status_mapping_version: str
    active_status_mapping_qualified_at_utc: datetime
    active_status_mapping_qualification_references: tuple[EvidenceReference, ...]
    active_status_mapping_sha256: str
    prerequisites_sha256: str
    sector_mapping_version: str | None
    liquidity_metric_id: str
    liquidity_evidence_version: str
    listing_history_metric_id: str
    listing_history_evidence_version: str
    classification_source_versions: tuple[str, ...]
    candidate_count: int
    member_count: int
    quarantine_count: int
    funnel_sha256: str
    members_sha256: str
    snapshot_sha256: str
    snapshot_record_sha256: str

    def __post_init__(self) -> None:
        if type(self.universe_snapshot_id) is not UUID or self.universe_snapshot_id.int == 0:
            raise SnapshotValidationError("universe_snapshot_id: non-nil UUID required")
        if self.snapshot_schema_version != _SCHEMA_VERSION:
            raise SnapshotValidationError(
                f"snapshot_schema_version: {_SCHEMA_VERSION} required"
            )
        if type(self.snapshot_kind) is not SnapshotKind:
            raise SnapshotValidationError("snapshot_kind: SnapshotKind required")
        if type(self.completeness) is not Completeness:
            raise SnapshotValidationError("completeness: Completeness required")
        if type(self.gateway_attempt_status) is not AttemptStatus:
            raise SnapshotValidationError(
                "gateway_attempt_status: AttemptStatus required"
            )
        if type(self.gateway_preflight_formal_ready) is not bool:
            raise SnapshotValidationError(
                "gateway_preflight_formal_ready: bool required"
            )
        runtime_window = self.gateway_runtime_evidence_window_seconds
        if (
            type(runtime_window) is not float
            or runtime_window != runtime_window
            or runtime_window in (float("inf"), float("-inf"))
            or runtime_window < 0
        ):
            raise SnapshotValidationError(
                "gateway_runtime_evidence_window_seconds: finite nonnegative float required"
            )
        for field_id in (
            "gateway_attempt_id",
            "provider",
            "provider_sdk_version",
            "opend_server_version",
            "market_data_delay_class",
            "gateway_preflight_market_data_delay_class",
            "active_status_mapping_provider",
            "active_status_mapping_provider_sdk_version",
            "active_status_mapping_opend_server_version",
            "active_status_mapping_version",
            "liquidity_metric_id",
            "liquidity_evidence_version",
            "listing_history_metric_id",
            "listing_history_evidence_version",
        ):
            _non_empty(getattr(self, field_id), field_id)
        for field_id in (
            "profile_version_id",
            "draft_id",
            "sector_mapping_version",
        ):
            _optional_string(getattr(self, field_id), field_id)
        _utc(self.created_at_utc, "created_at_utc")
        _utc(
            self.gateway_attempt_observed_at_utc,
            "gateway_attempt_observed_at_utc",
        )
        if type(self.gateway_preflight_as_of_session) is not date:
            raise SnapshotValidationError(
                "gateway_preflight_as_of_session: date required"
            )
        _utc(
            self.gateway_preflight_observed_at_utc,
            "gateway_preflight_observed_at_utc",
        )
        if self.provider_update_time is not None:
            _utc(self.provider_update_time, "provider_update_time")
        if self.gateway_preflight_provider_update_time is not None:
            _utc(
                self.gateway_preflight_provider_update_time,
                "gateway_preflight_provider_update_time",
            )
        _utc(
            self.active_status_mapping_qualified_at_utc,
            "active_status_mapping_qualified_at_utc",
        )
        for field_id in (
            "gateway_attempt_sha256",
            "market_state_consistency_sha256",
            "active_status_mapping_sha256",
            "prerequisites_sha256",
            "funnel_sha256",
            "members_sha256",
            "snapshot_sha256",
            "snapshot_record_sha256",
        ):
            _hash(getattr(self, field_id), field_id)
        _hash(self.profile_content_sha256, "profile_content_sha256", optional=True)
        _hash(self.draft_content_sha256, "draft_content_sha256", optional=True)
        references = _references(
            self.active_status_mapping_qualification_references,
            "active_status_mapping_qualification_references",
        )
        if not references:
            raise SnapshotValidationError(
                "active_status_mapping_qualification_references: required"
            )
        object.__setattr__(
            self, "active_status_mapping_qualification_references", references
        )
        object.__setattr__(
            self,
            "gateway_preflight_reason_codes",
            tuple(sorted(set(self.gateway_preflight_reason_codes))),
        )
        object.__setattr__(
            self,
            "gateway_attempt_reason_codes",
            tuple(sorted(set(self.gateway_attempt_reason_codes))),
        )
        object.__setattr__(
            self,
            "classification_source_versions",
            tuple(sorted(set(self.classification_source_versions))),
        )
        gateway_batches = tuple(self.gateway_batches)
        if any(type(item) is not ApiBatchRecord for item in gateway_batches):
            raise SnapshotValidationError(
                "gateway_batches: ApiBatchRecord values required"
            )
        identity_ledger = tuple(self.gateway_identity_ledger)
        if any(type(item) is not IdentityLedgerEntry for item in identity_ledger):
            raise SnapshotValidationError(
                "gateway_identity_ledger: IdentityLedgerEntry values required"
            )
        delay_evidence = tuple(self.market_data_delay_evidence)
        if any(type(item) is not ApiBatchRecord for item in delay_evidence):
            raise SnapshotValidationError(
                "market_data_delay_evidence: ApiBatchRecord values required"
            )
        if delay_evidence != tuple(
            batch for batch in gateway_batches if batch.endpoint == "qot_right_capture"
        ):
            raise SnapshotValidationError(
                "market_data_delay_evidence: qot_right_capture ledger projection mismatch"
            )
        probes = tuple(self.realtime_capability_probes)
        if any(type(item) is not RawApiBatch for item in probes):
            raise SnapshotValidationError(
                "realtime_capability_probes: RawApiBatch values required"
            )
        object.__setattr__(self, "gateway_batches", gateway_batches)
        object.__setattr__(self, "gateway_identity_ledger", identity_ledger)
        object.__setattr__(self, "market_data_delay_evidence", delay_evidence)
        object.__setattr__(self, "realtime_capability_probes", probes)
        if (
            self.gateway_preflight_as_of_session != self.as_of_session
            or self.gateway_preflight_observed_at_utc
            != self.gateway_attempt_observed_at_utc
            or self.gateway_preflight_provider_update_time
            != self.provider_update_time
            or self.gateway_preflight_market_data_delay_class
            != self.market_data_delay_class
            or self.provider != self.active_status_mapping_provider
            or self.provider_sdk_version
            != self.active_status_mapping_provider_sdk_version
            or self.opend_server_version
            != self.active_status_mapping_opend_server_version
        ):
            raise SnapshotValidationError(
                "gateway preflight: attempt/mapping provenance mismatch"
            )
        for field_id in ("candidate_count", "member_count", "quarantine_count"):
            value = getattr(self, field_id)
            if type(value) is not int or value < 0:
                raise SnapshotValidationError(
                    f"{field_id}: non-negative integer required"
                )
        if self.snapshot_kind is SnapshotKind.FORMAL:
            if (
                self.profile_version_id is None
                or self.profile_content_sha256 is None
                or self.draft_id is not None
                or self.draft_content_sha256 is not None
            ):
                raise SnapshotValidationError(
                    "FORMAL header requires profile and forbids draft"
                )
            if (
                self.completeness is not Completeness.COMPLETE
                or self.gateway_attempt_status is not AttemptStatus.SUCCEEDED
                or not self.gateway_preflight_formal_ready
                or self.gateway_preflight_reason_codes
                or self.gateway_attempt_reason_codes
            ):
                raise SnapshotValidationError(
                    "FORMAL header requires successful complete upstream attempt verdict"
                )
        elif (
            self.profile_version_id is not None
            or self.profile_content_sha256 is not None
            or self.draft_id is None
            or self.draft_content_sha256 is None
        ):
            raise SnapshotValidationError(
                "PREVIEW header requires draft and forbids profile"
            )

    @property
    def snapshot_content_sha256(self) -> str:
        return self.snapshot_sha256


@dataclass(frozen=True, slots=True)
class UniverseSnapshotRow:
    stock_id: str
    futu_code: str
    symbol: str
    name: str
    exchange_raw: str | None
    exchange_normalized: str | None
    security_type_raw: str | None
    security_class_normalized: str | None
    classification_evidence: tuple[SecurityClassificationEvidence, ...]
    delisting: bool | None
    suspension: bool | None
    security_status_raw: str | None
    active_status_decision: Decision | None
    active_status_reason_code: str | None
    active_status_evidence_references: tuple[EvidenceReference, ...]
    identity_decision: Decision | None
    identity_reason_code: str | None
    identity_evidence_references: tuple[EvidenceReference, ...]
    price_usd: Decimal | None
    price_observed_at_utc: datetime
    market_cap_usd: Decimal | None
    market_cap_observed_at_utc: datetime
    liquidity_metric_id: str
    liquidity_evidence_version: str
    avg_turnover_20d_usd: Decimal | None
    liquidity_window_end: date
    avg_volume_20d_shares: Decimal | None
    listing_history_metric_id: str
    listing_history_evidence_version: str
    listing_date: date | None
    listed_days: int | None
    listing_history_cross_check: tuple[str, ...]
    raw_industry: RawIndustryEvidence
    raw_plates: tuple[RawPlateEvidence, ...]
    sector_mapping_version: str | None
    field_decisions: tuple[FieldDecision, ...]
    first_exit_stage: str | None
    first_exit_reason_code: str | None
    is_member: bool
    is_quarantined: bool
    raw_evidence_references: tuple[EvidenceReference, ...]
    raw_evidence_sha256: str

    def __post_init__(self) -> None:
        for field_id in ("stock_id", "futu_code", "symbol", "name"):
            _non_empty(getattr(self, field_id), field_id)
        for field_id in (
            "exchange_raw",
            "exchange_normalized",
            "security_type_raw",
            "security_class_normalized",
            "security_status_raw",
            "active_status_reason_code",
            "identity_reason_code",
            "sector_mapping_version",
            "first_exit_stage",
            "first_exit_reason_code",
        ):
            _optional_string(getattr(self, field_id), field_id)
        for field_id in (
            "active_status_decision",
            "identity_decision",
        ):
            value = getattr(self, field_id)
            if value is not None and type(value) is not Decision:
                raise SnapshotValidationError(
                    f"{field_id}: Decision or None required"
                )
        for prefix in ("active_status", "identity"):
            decision = getattr(self, f"{prefix}_decision")
            reason = getattr(self, f"{prefix}_reason_code")
            if (decision is None) != (reason is None):
                raise SnapshotValidationError(
                    f"{prefix}: decision and reason must be present together"
                )
        _utc(self.price_observed_at_utc, "price_observed_at_utc")
        _utc(self.market_cap_observed_at_utc, "market_cap_observed_at_utc")
        if type(self.liquidity_window_end) is not date:
            raise SnapshotValidationError("liquidity_window_end: date required")
        for field_id in (
            "liquidity_metric_id",
            "liquidity_evidence_version",
            "listing_history_metric_id",
            "listing_history_evidence_version",
        ):
            _non_empty(getattr(self, field_id), field_id)
        for field_id in ("is_member", "is_quarantined"):
            if type(getattr(self, field_id)) is not bool:
                raise SnapshotValidationError(f"{field_id}: bool required")
        _hash(self.raw_evidence_sha256, "raw_evidence_sha256")
        for field_id in (
            "active_status_evidence_references",
            "identity_evidence_references",
            "raw_evidence_references",
        ):
            object.__setattr__(
                self, field_id, _references(getattr(self, field_id), field_id)
            )
        classifications = tuple(self.classification_evidence)
        if any(
            type(item) is not SecurityClassificationEvidence
            for item in classifications
        ):
            raise SnapshotValidationError(
                "classification_evidence: values required"
            )
        decisions = tuple(_freeze_field_decision(item) for item in self.field_decisions)
        if any(type(item) is not FieldDecision for item in decisions):
            raise SnapshotValidationError("field_decisions: values required")
        if tuple(item.field_id for item in decisions) != (
            "S1_IDENTITY_VALID",
            "S2_EXCHANGE_ALLOWED",
            "S3_SECURITY_CLASS_ALLOWED",
            "S4_ACTIVE_STATUS_ALLOWED",
            "S5_PRICE_ALLOWED",
            "S6_MARKET_CAP_ALLOWED",
            "S7_SECTOR_INDUSTRY_ALLOWED",
            "S8_LISTING_HISTORY_ALLOWED",
            "S9_LIQUIDITY_ALLOWED",
        ):
            raise SnapshotValidationError("field_decisions: fixed S1-S9 order required")
        object.__setattr__(self, "classification_evidence", classifications)
        object.__setattr__(self, "field_decisions", decisions)
        object.__setattr__(self, "raw_plates", tuple(self.raw_plates))
        object.__setattr__(
            self,
            "listing_history_cross_check",
            tuple(sorted(set(self.listing_history_cross_check))),
        )


def _row_matches_evaluation(
    row: UniverseSnapshotRow, evaluation: SecurityEvaluation
) -> bool:
    return (
        row.stock_id == evaluation.stock_id
        and row.futu_code == evaluation.futu_code
        and row.symbol == evaluation.symbol
        and row.name == evaluation.name
        and row.field_decisions == evaluation.field_decisions
        and row.first_exit_stage == evaluation.first_exit_stage
        and row.first_exit_reason_code == evaluation.first_exit_reason_code
        and row.is_member is evaluation.is_member
        and row.is_quarantined is evaluation.is_quarantined
    )


def _row_prerequisite(row: UniverseSnapshotRow) -> SecurityEvaluationPrerequisites:
    def normalized(
        decision: Decision | None,
        reason: str | None,
        references: tuple[EvidenceReference, ...],
    ) -> NormalizedPrerequisiteDecision | None:
        if decision is None or reason is None:
            return None
        return NormalizedPrerequisiteDecision(decision, reason, references)

    return SecurityEvaluationPrerequisites(
        row.stock_id,
        row.futu_code,
        normalized(
            row.active_status_decision,
            row.active_status_reason_code,
            row.active_status_evidence_references,
        ),
        normalized(
            row.identity_decision,
            row.identity_reason_code,
            row.identity_evidence_references,
        ),
    )


@dataclass(frozen=True, slots=True)
class UniverseSnapshot:
    header: UniverseSnapshotHeader
    rows: tuple[UniverseSnapshotRow, ...]
    funnel: UniverseFunnel

    def __post_init__(self) -> None:
        if type(self.header) is not UniverseSnapshotHeader:
            raise SnapshotValidationError("header: UniverseSnapshotHeader required")
        if type(self.funnel) is not UniverseFunnel:
            raise SnapshotValidationError("funnel: UniverseFunnel required")
        rows = tuple(self.rows)
        if any(type(item) is not UniverseSnapshotRow for item in rows):
            raise SnapshotValidationError("rows: UniverseSnapshotRow values required")
        ordered = tuple(sorted(rows, key=lambda row: (row.stock_id, row.futu_code)))
        if rows != ordered:
            raise SnapshotValidationError("rows: deterministic composite-key order required")
        keys = tuple((row.stock_id, row.futu_code) for row in rows)
        if len(keys) != len(set(keys)):
            raise SnapshotValidationError("rows: duplicate composite key")
        evaluations = tuple(self.funnel.evaluations)
        if (
            tuple(stage.stage_id for stage in self.funnel.stages)
            != _FUNNEL_STAGE_IDS
            or any(
                stage.stage_order != index
                for index, stage in enumerate(self.funnel.stages)
            )
        ):
            raise SnapshotValidationError(
                "funnel stages: fixed S0-S10 ID/order contract required"
            )
        if (
            len(evaluations) != len(rows)
            or any(type(item) is not SecurityEvaluation for item in evaluations)
            or any(
                not _row_matches_evaluation(row, evaluation)
                for row, evaluation in zip(rows, evaluations, strict=True)
            )
        ):
            raise SnapshotValidationError(
                "funnel: rows must exactly bind Task 6 evaluations"
            )
        expected_members = tuple(
            evaluation
            for row, evaluation in zip(rows, evaluations, strict=True)
            if row.is_member
        )
        if self.funnel.members != expected_members:
            raise SnapshotValidationError(
                "funnel: members must preserve frozen Task 6 membership flags"
            )
        if self.header.candidate_count != len(rows):
            raise SnapshotValidationError("candidate_count: rows mismatch")
        if self.header.member_count != sum(row.is_member for row in rows):
            raise SnapshotValidationError("member_count: rows mismatch")
        if self.header.quarantine_count != sum(
            row.is_quarantined for row in rows
        ):
            raise SnapshotValidationError("quarantine_count: rows mismatch")
        if self.header.funnel_sha256 != funnel_sha256(self.funnel):
            raise SnapshotValidationError("funnel_sha256: funnel mismatch")
        if self.header.prerequisites_sha256 != prerequisites_sha256(
            tuple(_row_prerequisite(row) for row in rows)
        ):
            raise SnapshotValidationError(
                "prerequisites_sha256: projected prerequisites mismatch"
            )
        if self.header.members_sha256 != members_sha256(rows):
            raise SnapshotValidationError("members_sha256: rows mismatch")
        if self.header.snapshot_sha256 != snapshot_content_sha256(self):
            raise SnapshotValidationError("snapshot_sha256: content mismatch")
        if self.header.snapshot_record_sha256 != snapshot_record_sha256(self):
            raise SnapshotValidationError("snapshot_record_sha256: record mismatch")
        object.__setattr__(self, "rows", rows)


def _header_payload(
    header: UniverseSnapshotHeader, *, omit: frozenset[str] = frozenset()
) -> dict[str, object]:
    return {
        field.name: _canonical(getattr(header, field.name))
        for field in fields(header)
        if field.name not in omit
    }


def _content_payload(
    header: UniverseSnapshotHeader,
    rows: Sequence[UniverseSnapshotRow],
    funnel: UniverseFunnel,
) -> dict[str, object]:
    return {
        "header": _header_payload(
            header,
            omit=frozenset(
                {
                    "universe_snapshot_id",
                    "created_at_utc",
                    "gateway_attempt_id",
                    "gateway_attempt_sha256",
                    "snapshot_sha256",
                    "snapshot_record_sha256",
                }
            ),
        ),
        "rows": [_canonical(row) for row in rows],
        "funnel": _canonical(funnel),
    }


def _record_payload(
    header: UniverseSnapshotHeader,
    rows: Sequence[UniverseSnapshotRow],
    funnel: UniverseFunnel,
) -> dict[str, object]:
    return {
        "header": _header_payload(
            header, omit=frozenset({"snapshot_record_sha256"})
        ),
        "rows": [_canonical(row) for row in rows],
        "funnel": _canonical(funnel),
    }


def members_sha256(rows: Sequence[UniverseSnapshotRow]) -> str:
    values = tuple(rows)
    if any(type(row) is not UniverseSnapshotRow for row in values):
        raise SnapshotValidationError("rows: UniverseSnapshotRow values required")
    keys = tuple((row.stock_id, row.futu_code) for row in values)
    if len(keys) != len(set(keys)):
        raise SnapshotValidationError("rows: duplicate composite key")
    members = sorted(
        (row.stock_id, row.futu_code) for row in values if row.is_member
    )
    return canonical_hash(
        {
            "members": [
                {"stock_id": stock_id, "futu_code": futu_code}
                for stock_id, futu_code in members
            ]
        }
    )


def snapshot_content_sha256(snapshot: UniverseSnapshot) -> str:
    if type(snapshot) is not UniverseSnapshot:
        raise SnapshotValidationError("snapshot: UniverseSnapshot required")
    return canonical_hash(_content_payload(snapshot.header, snapshot.rows, snapshot.funnel))


def snapshot_record_sha256(snapshot: UniverseSnapshot) -> str:
    if type(snapshot) is not UniverseSnapshot:
        raise SnapshotValidationError("snapshot: UniverseSnapshot required")
    return canonical_hash(_record_payload(snapshot.header, snapshot.rows, snapshot.funnel))


def _decision_projection(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _row_from_inputs(
    evaluation: SecurityEvaluation,
    evidence: object,
    prerequisite: SecurityEvaluationPrerequisites,
    sector_mapping_version: str | None,
) -> UniverseSnapshotRow:
    from .evidence import UniverseSecurityEvidence

    if type(evidence) is not UniverseSecurityEvidence:
        raise SnapshotValidationError("evidence: UniverseSecurityEvidence required")
    identity = prerequisite.identity
    active = prerequisite.active_status
    decisions = evaluation.field_decisions
    return UniverseSnapshotRow(
        stock_id=evaluation.stock_id,
        futu_code=evaluation.futu_code,
        symbol=evaluation.symbol,
        name=evaluation.name,
        exchange_raw=evidence.exchange_raw,
        exchange_normalized=_decision_projection(decisions[1].normalized_value),
        security_type_raw=evidence.security_type_raw,
        security_class_normalized=_decision_projection(
            decisions[2].normalized_value
        ),
        classification_evidence=evidence.classification_evidence,
        delisting=evidence.delisting,
        suspension=evidence.suspension,
        security_status_raw=evidence.security_status_raw,
        active_status_decision=None if active is None else active.decision,
        active_status_reason_code=None if active is None else active.reason_code,
        active_status_evidence_references=(
            () if active is None else active.evidence_references
        ),
        identity_decision=None if identity is None else identity.decision,
        identity_reason_code=None if identity is None else identity.reason_code,
        identity_evidence_references=(
            () if identity is None else identity.evidence_references
        ),
        price_usd=evidence.price_usd,
        price_observed_at_utc=evidence.provenance.observed_at_utc,
        market_cap_usd=evidence.market_cap_usd,
        market_cap_observed_at_utc=evidence.provenance.observed_at_utc,
        liquidity_metric_id=evidence.liquidity.metric_id,
        liquidity_evidence_version=evidence.liquidity.evidence_version,
        avg_turnover_20d_usd=evidence.liquidity.avg_turnover_20d_usd,
        liquidity_window_end=evidence.liquidity.provenance.observed_at_utc.date(),
        avg_volume_20d_shares=evidence.liquidity.avg_volume_20d_shares,
        listing_history_metric_id=evidence.listing_history.metric_id,
        listing_history_evidence_version=evidence.listing_history.evidence_version,
        listing_date=evidence.listing_history.listing_date,
        listed_days=evidence.listing_history.listed_days,
        listing_history_cross_check=evidence.listing_history.reason_codes,
        raw_industry=evidence.raw_industry,
        raw_plates=evidence.raw_plates,
        sector_mapping_version=sector_mapping_version,
        field_decisions=evaluation.field_decisions,
        first_exit_stage=evaluation.first_exit_stage,
        first_exit_reason_code=evaluation.first_exit_reason_code,
        is_member=evaluation.is_member,
        is_quarantined=evaluation.is_quarantined,
        raw_evidence_references=evidence.provenance.references,
        raw_evidence_sha256=evidence_record_sha256(evidence),
    )


def _assert_prerequisite_binding(
    evaluation: SecurityEvaluation,
    prerequisite: SecurityEvaluationPrerequisites,
) -> None:
    for decision_index, normalized, label in (
        (0, prerequisite.identity, "Identity"),
        (3, prerequisite.active_status, "Active"),
    ):
        field = evaluation.field_decisions[decision_index]
        if normalized is None:
            raise SnapshotValidationError(
                f"{label} prerequisite: normalized decision required"
            )
        if (
            field.decision is not normalized.decision
            or field.reason_code != normalized.reason_code
            or field.evidence_references != normalized.evidence_references
        ):
            raise SnapshotValidationError(
                f"{label} prerequisite projection mismatch"
            )


def _assert_preflight_binding(attempt: GatewayAttempt) -> None:
    preflight = attempt.preflight
    mapping = attempt.active_status_mapping
    contract = attempt.market_state_consistency_contract
    if (
        preflight.as_of_session != attempt.as_of_session
        or preflight.observed_at_utc != attempt.observed_at_utc
        or preflight.provider_update_time != attempt.provider_update_time
        or preflight.market_data_delay_class != attempt.market_data_delay_class
        or preflight.provider != mapping.provider
        or preflight.provider_sdk_version != mapping.provider_sdk_version
        or preflight.opend_server_version != mapping.opend_server_version
        or preflight.provider != contract.provider
        or preflight.provider_sdk_version != contract.provider_sdk_version
        or preflight.opend_server_version != contract.opend_server_version
    ):
        raise SnapshotValidationError(
            "gateway preflight: attempt/mapping/contract provenance mismatch"
        )


def _frozen_evaluation(value: SecurityEvaluation) -> SecurityEvaluation:
    evaluation = object.__new__(SecurityEvaluation)
    for field_id in (
        "stock_id",
        "futu_code",
        "symbol",
        "name",
        "first_exit_stage",
        "first_exit_reason_code",
        "is_member",
        "is_quarantined",
    ):
        object.__setattr__(evaluation, field_id, getattr(value, field_id))
    object.__setattr__(
        evaluation,
        "field_decisions",
        tuple(_freeze_field_decision(item) for item in value.field_decisions),
    )
    return evaluation


def _frozen_funnel(
    source: UniverseFunnel, evaluations: tuple[SecurityEvaluation, ...]
) -> UniverseFunnel:
    by_key = {(item.stock_id, item.futu_code): item for item in evaluations}
    member_keys = tuple((item.stock_id, item.futu_code) for item in source.members)
    funnel = object.__new__(UniverseFunnel)
    object.__setattr__(funnel, "evaluations", evaluations)
    object.__setattr__(funnel, "stages", tuple(source.stages))
    object.__setattr__(funnel, "members", tuple(by_key[key] for key in member_keys))
    return funnel


def build_snapshot(
    *,
    kind: SnapshotKind,
    profile: UniverseProfile | None,
    draft: UniverseDraft | None,
    gateway_attempt: GatewayAttempt,
    evaluations: Sequence[SecurityEvaluation],
    funnel: UniverseFunnel,
    universe_snapshot_id: UUID,
    created_at_utc: datetime,
) -> UniverseSnapshot:
    """Copy complete upstream facts into one deterministic immutable snapshot."""

    if type(kind) is not SnapshotKind:
        raise SnapshotValidationError("kind: SnapshotKind required")
    if type(gateway_attempt) is not GatewayAttempt:
        raise SnapshotValidationError("gateway_attempt: GatewayAttempt required")
    _assert_preflight_binding(gateway_attempt)
    if type(funnel) is not UniverseFunnel:
        raise SnapshotValidationError("funnel: UniverseFunnel required")
    if type(universe_snapshot_id) is not UUID or universe_snapshot_id.int == 0:
        raise SnapshotValidationError("universe_snapshot_id: non-nil UUID required")
    _utc(created_at_utc, "created_at_utc")
    if kind is SnapshotKind.FORMAL:
        if type(profile) is not UniverseProfile or draft is not None:
            raise SnapshotValidationError(
                "FORMAL snapshot requires profile and forbids draft"
            )
        if (
            profile.record_state is not RecordState.PUBLISHED
            or profile.content_sha256 is None
        ):
            raise SnapshotValidationError("FORMAL profile must be published")
        if (
            gateway_attempt.attempt_status is not AttemptStatus.SUCCEEDED
            or gateway_attempt.completeness is not Completeness.COMPLETE
            or not gateway_attempt.preflight.formal_ready
            or gateway_attempt.preflight.reason_codes
            or gateway_attempt.reason_codes
        ):
            raise SnapshotValidationError(
                "FORMAL snapshot requires successful complete upstream attempt verdict"
            )
    else:
        if type(draft) is not UniverseDraft or profile is not None:
            raise SnapshotValidationError(
                "PREVIEW snapshot requires draft and forbids profile"
            )

    evaluation_values = tuple(evaluations)
    if not evaluation_values or any(
        type(item) is not SecurityEvaluation for item in evaluation_values
    ):
        raise SnapshotValidationError(
            "evaluations: non-empty SecurityEvaluation sequence required"
        )
    evaluation_keys = tuple(
        (item.stock_id, item.futu_code) for item in evaluation_values
    )
    if len(evaluation_keys) != len(set(evaluation_keys)):
        raise SnapshotValidationError("evaluations: duplicate composite key")
    ordered_evaluations = tuple(
        sorted(evaluation_values, key=lambda item: (item.stock_id, item.futu_code))
    )
    if ordered_evaluations != funnel.evaluations:
        raise SnapshotValidationError(
            "funnel: must exactly bind supplied Task 6 evaluations"
        )
    ordered_evaluations = tuple(
        _frozen_evaluation(item) for item in ordered_evaluations
    )
    funnel = _frozen_funnel(funnel, ordered_evaluations)
    evidence_by_key = {
        (item.stock_id, item.futu_code): item for item in gateway_attempt.evidence
    }
    prerequisite_by_key = {
        (item.stock_id, item.futu_code): item
        for item in gateway_attempt.prerequisites
    }
    expected_keys = set(evaluation_keys)
    if expected_keys != set(evidence_by_key) or expected_keys != set(
        prerequisite_by_key
    ):
        message = (
            "FORMAL partial snapshot or evidence/prerequisite composite binding mismatch"
            if kind is SnapshotKind.FORMAL
            else "evidence/prerequisite composite binding mismatch"
        )
        raise SnapshotValidationError(message)

    selected = profile if profile is not None else draft
    assert selected is not None
    rows: list[UniverseSnapshotRow] = []
    for evaluation in ordered_evaluations:
        key = (evaluation.stock_id, evaluation.futu_code)
        evidence = evidence_by_key[key]
        prerequisite = prerequisite_by_key[key]
        if (evaluation.symbol, evaluation.name) != (evidence.symbol, evidence.name):
            raise SnapshotValidationError(
                "evaluation/evidence composite identity fields mismatch"
            )
        _assert_prerequisite_binding(evaluation, prerequisite)
        rows.append(
            _row_from_inputs(
                evaluation,
                evidence,
                prerequisite,
                selected.filters.sector_mapping_version,
            )
        )
    row_values = tuple(rows)
    mapping = gateway_attempt.active_status_mapping
    classification_versions = tuple(
        sorted(
            {
                item.source_version
                for evidence in gateway_attempt.evidence
                for item in evidence.classification_evidence
            }
        )
    )
    attempt_payload = _canonical(gateway_attempt)
    if not isinstance(attempt_payload, dict):  # pragma: no cover
        raise SnapshotValidationError("gateway_attempt: canonical mapping required")
    header = UniverseSnapshotHeader(
        universe_snapshot_id=universe_snapshot_id,
        snapshot_schema_version=_SCHEMA_VERSION,
        snapshot_kind=kind,
        completeness=gateway_attempt.completeness,
        profile_version_id=None if profile is None else profile.profile_version_id,
        profile_content_sha256=None if profile is None else profile.content_sha256,
        draft_id=None if draft is None else draft.draft_id,
        draft_content_sha256=None if draft is None else draft.draft_content_sha256,
        as_of_session=gateway_attempt.as_of_session,
        created_at_utc=created_at_utc,
        gateway_attempt_id=gateway_attempt.attempt_id,
        gateway_attempt_observed_at_utc=gateway_attempt.observed_at_utc,
        provider_update_time=gateway_attempt.provider_update_time,
        gateway_attempt_status=gateway_attempt.attempt_status,
        gateway_preflight_as_of_session=gateway_attempt.preflight.as_of_session,
        gateway_preflight_observed_at_utc=(
            gateway_attempt.preflight.observed_at_utc
        ),
        gateway_preflight_provider_update_time=(
            gateway_attempt.preflight.provider_update_time
        ),
        gateway_preflight_market_data_delay_class=(
            gateway_attempt.preflight.market_data_delay_class
        ),
        gateway_preflight_formal_ready=gateway_attempt.preflight.formal_ready,
        gateway_preflight_reason_codes=gateway_attempt.preflight.reason_codes,
        gateway_runtime_evidence_window_seconds=(
            gateway_attempt.runtime_evidence_window_seconds
        ),
        gateway_attempt_reason_codes=gateway_attempt.reason_codes,
        gateway_attempt_sha256=canonical_hash(
            {"gateway_attempt": attempt_payload}
        ),
        provider=gateway_attempt.preflight.provider,
        provider_sdk_version=gateway_attempt.preflight.provider_sdk_version,
        opend_server_version=gateway_attempt.preflight.opend_server_version,
        gateway_batches=gateway_attempt.batches,
        gateway_identity_ledger=gateway_attempt.identity_ledger,
        market_data_delay_evidence=tuple(
            batch
            for batch in gateway_attempt.batches
            if batch.endpoint == "qot_right_capture"
        ),
        realtime_capability_probes=gateway_attempt.realtime_capability_probes,
        market_data_delay_class=gateway_attempt.market_data_delay_class,
        market_state_consistency_sha256=(
            gateway_attempt.market_state_consistency_contract.canonical_sha256
        ),
        active_status_mapping_provider=mapping.provider,
        active_status_mapping_provider_sdk_version=mapping.provider_sdk_version,
        active_status_mapping_opend_server_version=mapping.opend_server_version,
        active_status_mapping_version=mapping.mapping_version,
        active_status_mapping_qualified_at_utc=mapping.qualified_at_utc,
        active_status_mapping_qualification_references=(
            mapping.qualification_references
        ),
        active_status_mapping_sha256=mapping.active_status_mapping_sha256,
        prerequisites_sha256=gateway_attempt.prerequisites_sha256,
        sector_mapping_version=selected.filters.sector_mapping_version,
        liquidity_metric_id=selected.filters.liquidity_metric_id,
        liquidity_evidence_version=selected.filters.liquidity_evidence_version,
        listing_history_metric_id=selected.filters.listing_history_metric_id,
        listing_history_evidence_version=(
            selected.filters.listing_history_evidence_version
        ),
        classification_source_versions=classification_versions,
        candidate_count=len(row_values),
        member_count=sum(row.is_member for row in row_values),
        quarantine_count=sum(row.is_quarantined for row in row_values),
        funnel_sha256=funnel_sha256(funnel),
        members_sha256=members_sha256(row_values),
        snapshot_sha256="0" * 64,
        snapshot_record_sha256="0" * 64,
    )
    content_hash = canonical_hash(_content_payload(header, row_values, funnel))
    header = UniverseSnapshotHeader(
        **{
            **{field.name: getattr(header, field.name) for field in fields(header)},
            "snapshot_sha256": content_hash,
        }
    )
    record_hash = canonical_hash(_record_payload(header, row_values, funnel))
    header = UniverseSnapshotHeader(
        **{
            **{field.name: getattr(header, field.name) for field in fields(header)},
            "snapshot_record_sha256": record_hash,
        }
    )
    return UniverseSnapshot(header, row_values, funnel)


def _canonical_json_bytes(snapshot: UniverseSnapshot) -> bytes:
    payload = {
        "header": _header_payload(snapshot.header),
        "rows": [_canonical(row) for row in snapshot.rows],
        "funnel": _canonical(snapshot.funnel),
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _required(mapping: Mapping[str, object], key: str) -> object:
    if key not in mapping:
        raise SnapshotValidationError(f"missing field: {key}")
    return mapping[key]


def _reference_from(value: object) -> EvidenceReference:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("reference: mapping required")
    return EvidenceReference(
        str(_required(value, "source_id")),
        str(_required(value, "source_locator")),
        str(_required(value, "source_record_sha256")),
    )


def _classification_from(value: object) -> SecurityClassificationEvidence:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("classification: mapping required")
    reference_value = _required(value, "reference")
    observed = _decode_audit(_required(value, "observed_at_utc"))
    if not isinstance(observed, datetime):
        raise SnapshotValidationError("classification observed_at_utc required")
    return SecurityClassificationEvidence(
        normalized_class=str(_required(value, "normalized_class")),
        provider=str(_required(value, "provider")),
        provider_value=str(_required(value, "provider_value")),
        observed_at_utc=observed,
        source_version=str(_required(value, "source_version")),
        source_record_sha256=str(_required(value, "source_record_sha256")),
        confidence=str(_required(value, "confidence")),
        notes=str(_required(value, "notes")),
        reference=(
            None if reference_value is None else _reference_from(reference_value)
        ),
        verified_by=(
            None
            if _required(value, "verified_by") is None
            else str(_required(value, "verified_by"))
        ),
    )


def _provenance_from(value: object) -> object:
    from .evidence import EvidenceProvenance

    if not isinstance(value, Mapping):
        raise SnapshotValidationError("provenance: mapping required")
    observed = _decode_audit(_required(value, "observed_at_utc"))
    if not isinstance(observed, datetime):
        raise SnapshotValidationError("provenance observed_at_utc required")
    references = _tuple_from(_required(value, "references"), "provenance references")
    return EvidenceProvenance(
        provider=str(_required(value, "provider")),
        provider_version=str(_required(value, "provider_version")),
        source_version=str(_required(value, "source_version")),
        schema_version=str(_required(value, "schema_version")),
        observed_at_utc=observed,
        references=tuple(_reference_from(item) for item in references),
    )


def _raw_industry_from(value: object) -> RawIndustryEvidence:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("raw_industry: mapping required")
    raw_value = _required(value, "raw_value")
    return RawIndustryEvidence(
        None if raw_value is None else str(raw_value),
        _provenance_from(_required(value, "provenance")),  # type: ignore[arg-type]
    )


def _raw_plate_from(value: object) -> RawPlateEvidence:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("raw_plate: mapping required")
    return RawPlateEvidence(
        str(_required(value, "plate_code")),
        str(_required(value, "plate_name")),
        str(_required(value, "plate_type")),
        _provenance_from(_required(value, "provenance")),  # type: ignore[arg-type]
    )


def _field_decision_from(value: object) -> FieldDecision:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("field_decision: mapping required")
    references = _tuple_from(
        _required(value, "evidence_references"),
        "field_decision evidence_references",
    )
    return FieldDecision(
        field_id=str(_required(value, "field_id")),
        raw_value=_decode_audit(_required(value, "raw_value")),
        normalized_value=_decode_audit(_required(value, "normalized_value")),
        operator=(
            None
            if _required(value, "operator") is None
            else str(_required(value, "operator"))
        ),
        threshold=_decode_audit(_required(value, "threshold")),
        decision=Decision(str(_required(value, "decision"))),
        reason_code=str(_required(value, "reason_code")),
        evidence_source=(
            None
            if _required(value, "evidence_source") is None
            else str(_required(value, "evidence_source"))
        ),
        evidence_observed_at_utc=_decode_audit(
            _required(value, "evidence_observed_at_utc")
        ),
        evidence_version=(
            None
            if _required(value, "evidence_version") is None
            else str(_required(value, "evidence_version"))
        ),
        evidence_references=tuple(_reference_from(item) for item in references),
    )


def _batch_from(value: object) -> ApiBatchRecord:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("batch: mapping required")
    acquired = _decode_audit(_required(value, "acquired_at_utc"))
    if not isinstance(acquired, datetime):
        raise SnapshotValidationError("batch acquired_at_utc required")
    page_index = _required(value, "page_index")
    return ApiBatchRecord(
        endpoint=str(_required(value, "endpoint")),
        batch_index=int(_required(value, "batch_index")),
        request_hash=str(_required(value, "request_hash")),
        response_hash=str(_required(value, "response_hash")),
        acquired_at_utc=acquired,
        page_index=None if page_index is None else int(page_index),
    )


def _identity_ledger_from(value: object) -> IdentityLedgerEntry:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("identity ledger: mapping required")
    stock_ids = _tuple_from(
        _required(value, "competing_stock_ids"), "competing_stock_ids"
    )
    codes = _tuple_from(
        _required(value, "competing_futu_codes"), "competing_futu_codes"
    )
    references = _tuple_from(
        _required(value, "evidence_references"),
        "identity ledger evidence_references",
    )
    return IdentityLedgerEntry(
        stock_id=str(_required(value, "stock_id")),
        futu_code=str(_required(value, "futu_code")),
        decision=Decision(str(_required(value, "decision"))),
        reason_code=str(_required(value, "reason_code")),
        competing_stock_ids=tuple(str(item) for item in stock_ids),
        competing_futu_codes=tuple(str(item) for item in codes),
        evidence_references=tuple(_reference_from(item) for item in references),
        reconciliation_completed=_required(
            value, "reconciliation_completed"
        ),  # type: ignore[arg-type]
    )


def _probe_from(value: object) -> RawApiBatch:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("probe: mapping required")
    acquired = _decode_audit(_required(value, "acquired_at_utc"))
    if not isinstance(acquired, datetime):
        raise SnapshotValidationError("probe acquired_at_utc required")
    request = _decode_audit(_required(value, "raw_request"))
    response = _decode_audit(_required(value, "raw_response"))
    if not isinstance(request, Mapping) or not isinstance(response, Mapping):
        raise SnapshotValidationError("probe request/response mappings required")
    return RawApiBatch(
        endpoint=str(_required(value, "endpoint")),
        batch_index=int(_required(value, "batch_index")),
        raw_request=request,
        raw_response=response,
        request_hash=str(_required(value, "request_hash")),
        response_hash=str(_required(value, "response_hash")),
        ret_code=_decode_audit(_required(value, "ret_code")),
        acquisition_status=str(_required(value, "acquisition_status")),
        acquired_at_utc=acquired,
    )


def _row_from_payload(value: object) -> UniverseSnapshotRow:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("row: mapping required")

    def optional_text(key: str) -> str | None:
        item = _required(value, key)
        return None if item is None else str(item)

    def optional_decimal(key: str) -> Decimal | None:
        item = _decode_audit(_required(value, key))
        if item is not None and not isinstance(item, Decimal):
            raise SnapshotValidationError(f"{key}: Decimal or None required")
        return item

    def references(key: str) -> tuple[EvidenceReference, ...]:
        items = _tuple_from(_required(value, key), key)
        return tuple(_reference_from(item) for item in items)

    classifications = _tuple_from(
        _required(value, "classification_evidence"), "classification_evidence"
    )
    plates = _tuple_from(_required(value, "raw_plates"), "raw_plates")
    decisions = _tuple_from(
        _required(value, "field_decisions"), "field_decisions"
    )
    cross_check = _tuple_from(
        _required(value, "listing_history_cross_check"),
        "listing_history_cross_check",
    )
    price_observed = _decode_audit(_required(value, "price_observed_at_utc"))
    cap_observed = _decode_audit(_required(value, "market_cap_observed_at_utc"))
    window_end = _decode_audit(_required(value, "liquidity_window_end"))
    listing_date = _decode_audit(_required(value, "listing_date"))
    if not isinstance(price_observed, datetime) or not isinstance(cap_observed, datetime):
        raise SnapshotValidationError("row observed timestamps required")
    if not isinstance(window_end, date):
        raise SnapshotValidationError("liquidity_window_end required")
    if listing_date is not None and not isinstance(listing_date, date):
        raise SnapshotValidationError("listing_date: date or None required")
    active_decision = _required(value, "active_status_decision")
    identity_decision = _required(value, "identity_decision")
    listed_days = _required(value, "listed_days")
    return UniverseSnapshotRow(
        stock_id=str(_required(value, "stock_id")),
        futu_code=str(_required(value, "futu_code")),
        symbol=str(_required(value, "symbol")),
        name=str(_required(value, "name")),
        exchange_raw=optional_text("exchange_raw"),
        exchange_normalized=optional_text("exchange_normalized"),
        security_type_raw=optional_text("security_type_raw"),
        security_class_normalized=optional_text("security_class_normalized"),
        classification_evidence=tuple(
            _classification_from(item) for item in classifications
        ),
        delisting=_required(value, "delisting"),  # type: ignore[arg-type]
        suspension=_required(value, "suspension"),  # type: ignore[arg-type]
        security_status_raw=optional_text("security_status_raw"),
        active_status_decision=(
            None if active_decision is None else Decision(str(active_decision))
        ),
        active_status_reason_code=optional_text("active_status_reason_code"),
        active_status_evidence_references=references(
            "active_status_evidence_references"
        ),
        identity_decision=(
            None if identity_decision is None else Decision(str(identity_decision))
        ),
        identity_reason_code=optional_text("identity_reason_code"),
        identity_evidence_references=references("identity_evidence_references"),
        price_usd=optional_decimal("price_usd"),
        price_observed_at_utc=price_observed,
        market_cap_usd=optional_decimal("market_cap_usd"),
        market_cap_observed_at_utc=cap_observed,
        liquidity_metric_id=str(_required(value, "liquidity_metric_id")),
        liquidity_evidence_version=str(
            _required(value, "liquidity_evidence_version")
        ),
        avg_turnover_20d_usd=optional_decimal("avg_turnover_20d_usd"),
        liquidity_window_end=window_end,
        avg_volume_20d_shares=optional_decimal("avg_volume_20d_shares"),
        listing_history_metric_id=str(
            _required(value, "listing_history_metric_id")
        ),
        listing_history_evidence_version=str(
            _required(value, "listing_history_evidence_version")
        ),
        listing_date=listing_date,
        listed_days=None if listed_days is None else int(listed_days),
        listing_history_cross_check=tuple(str(item) for item in cross_check),
        raw_industry=_raw_industry_from(_required(value, "raw_industry")),
        raw_plates=tuple(_raw_plate_from(item) for item in plates),
        sector_mapping_version=optional_text("sector_mapping_version"),
        field_decisions=tuple(_field_decision_from(item) for item in decisions),
        first_exit_stage=optional_text("first_exit_stage"),
        first_exit_reason_code=optional_text("first_exit_reason_code"),
        is_member=_required(value, "is_member"),  # type: ignore[arg-type]
        is_quarantined=_required(value, "is_quarantined"),  # type: ignore[arg-type]
        raw_evidence_references=references("raw_evidence_references"),
        raw_evidence_sha256=str(_required(value, "raw_evidence_sha256")),
    )


def _header_from_payload(value: object) -> UniverseSnapshotHeader:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("header: mapping required")

    def optional_text(key: str) -> str | None:
        item = _required(value, key)
        return None if item is None else str(item)

    def decoded(key: str, expected: type[Any]) -> Any:
        item = _decode_audit(_required(value, key))
        if not isinstance(item, expected):
            raise SnapshotValidationError(f"{key}: {expected.__name__} required")
        return item

    refs = _tuple_from(
        _required(value, "active_status_mapping_qualification_references"),
        "active_status_mapping_qualification_references",
    )
    batches = _tuple_from(
        _required(value, "market_data_delay_evidence"),
        "market_data_delay_evidence",
    )
    gateway_batches = _tuple_from(
        _required(value, "gateway_batches"), "gateway_batches"
    )
    identity_ledger = _tuple_from(
        _required(value, "gateway_identity_ledger"), "gateway_identity_ledger"
    )
    probes = _tuple_from(
        _required(value, "realtime_capability_probes"),
        "realtime_capability_probes",
    )
    preflight_reasons = _tuple_from(
        _required(value, "gateway_preflight_reason_codes"),
        "gateway_preflight_reason_codes",
    )
    reasons = _tuple_from(
        _required(value, "gateway_attempt_reason_codes"),
        "gateway_attempt_reason_codes",
    )
    versions = _tuple_from(
        _required(value, "classification_source_versions"),
        "classification_source_versions",
    )
    provider_update = _decode_audit(_required(value, "provider_update_time"))
    if provider_update is not None and not isinstance(provider_update, datetime):
        raise SnapshotValidationError("provider_update_time: datetime or None required")
    preflight_provider_update = _decode_audit(
        _required(value, "gateway_preflight_provider_update_time")
    )
    if preflight_provider_update is not None and not isinstance(
        preflight_provider_update, datetime
    ):
        raise SnapshotValidationError(
            "gateway_preflight_provider_update_time: datetime or None required"
        )
    runtime_window = _decode_audit(
        _required(value, "gateway_runtime_evidence_window_seconds")
    )
    if type(runtime_window) is not float:
        raise SnapshotValidationError(
            "gateway_runtime_evidence_window_seconds: float required"
        )
    return UniverseSnapshotHeader(
        universe_snapshot_id=decoded("universe_snapshot_id", UUID),
        snapshot_schema_version=str(_required(value, "snapshot_schema_version")),
        snapshot_kind=SnapshotKind(str(_required(value, "snapshot_kind"))),
        completeness=Completeness(str(_required(value, "completeness"))),
        profile_version_id=optional_text("profile_version_id"),
        profile_content_sha256=optional_text("profile_content_sha256"),
        draft_id=optional_text("draft_id"),
        draft_content_sha256=optional_text("draft_content_sha256"),
        as_of_session=decoded("as_of_session", date),
        created_at_utc=decoded("created_at_utc", datetime),
        gateway_attempt_id=str(_required(value, "gateway_attempt_id")),
        gateway_attempt_observed_at_utc=decoded(
            "gateway_attempt_observed_at_utc", datetime
        ),
        provider_update_time=provider_update,
        gateway_attempt_status=AttemptStatus(
            str(_required(value, "gateway_attempt_status"))
        ),
        gateway_preflight_as_of_session=decoded(
            "gateway_preflight_as_of_session", date
        ),
        gateway_preflight_observed_at_utc=decoded(
            "gateway_preflight_observed_at_utc", datetime
        ),
        gateway_preflight_provider_update_time=preflight_provider_update,
        gateway_preflight_market_data_delay_class=str(
            _required(value, "gateway_preflight_market_data_delay_class")
        ),
        gateway_preflight_formal_ready=_required(
            value, "gateway_preflight_formal_ready"
        ),  # type: ignore[arg-type]
        gateway_preflight_reason_codes=tuple(
            str(item) for item in preflight_reasons
        ),
        gateway_runtime_evidence_window_seconds=runtime_window,
        gateway_attempt_reason_codes=tuple(str(item) for item in reasons),
        gateway_attempt_sha256=str(_required(value, "gateway_attempt_sha256")),
        provider=str(_required(value, "provider")),
        provider_sdk_version=str(_required(value, "provider_sdk_version")),
        opend_server_version=str(_required(value, "opend_server_version")),
        gateway_batches=tuple(_batch_from(item) for item in gateway_batches),
        gateway_identity_ledger=tuple(
            _identity_ledger_from(item) for item in identity_ledger
        ),
        market_data_delay_evidence=tuple(_batch_from(item) for item in batches),
        realtime_capability_probes=tuple(_probe_from(item) for item in probes),
        market_data_delay_class=str(_required(value, "market_data_delay_class")),
        market_state_consistency_sha256=str(
            _required(value, "market_state_consistency_sha256")
        ),
        active_status_mapping_provider=str(
            _required(value, "active_status_mapping_provider")
        ),
        active_status_mapping_provider_sdk_version=str(
            _required(value, "active_status_mapping_provider_sdk_version")
        ),
        active_status_mapping_opend_server_version=str(
            _required(value, "active_status_mapping_opend_server_version")
        ),
        active_status_mapping_version=str(
            _required(value, "active_status_mapping_version")
        ),
        active_status_mapping_qualified_at_utc=decoded(
            "active_status_mapping_qualified_at_utc", datetime
        ),
        active_status_mapping_qualification_references=tuple(
            _reference_from(item) for item in refs
        ),
        active_status_mapping_sha256=str(
            _required(value, "active_status_mapping_sha256")
        ),
        prerequisites_sha256=str(_required(value, "prerequisites_sha256")),
        sector_mapping_version=optional_text("sector_mapping_version"),
        liquidity_metric_id=str(_required(value, "liquidity_metric_id")),
        liquidity_evidence_version=str(
            _required(value, "liquidity_evidence_version")
        ),
        listing_history_metric_id=str(
            _required(value, "listing_history_metric_id")
        ),
        listing_history_evidence_version=str(
            _required(value, "listing_history_evidence_version")
        ),
        classification_source_versions=tuple(str(item) for item in versions),
        candidate_count=int(_required(value, "candidate_count")),
        member_count=int(_required(value, "member_count")),
        quarantine_count=int(_required(value, "quarantine_count")),
        funnel_sha256=str(_required(value, "funnel_sha256")),
        members_sha256=str(_required(value, "members_sha256")),
        snapshot_sha256=str(_required(value, "snapshot_sha256")),
        snapshot_record_sha256=str(
            _required(value, "snapshot_record_sha256")
        ),
    )


def _evaluation_from_payload(value: object) -> SecurityEvaluation:
    """Parse frozen Task 6 facts without invoking Task 6 derivation."""

    if not isinstance(value, Mapping):
        raise SnapshotValidationError("funnel evaluation: mapping required")
    decisions = tuple(
        _field_decision_from(item)
        for item in _tuple_from(
            _required(value, "field_decisions"),
            "funnel evaluation field_decisions",
        )
    )
    first_exit_stage = _required(value, "first_exit_stage")
    first_exit_reason = _required(value, "first_exit_reason_code")
    is_member = _required(value, "is_member")
    is_quarantined = _required(value, "is_quarantined")
    if first_exit_stage is not None and type(first_exit_stage) is not str:
        raise SnapshotValidationError("first_exit_stage: string or None required")
    if first_exit_reason is not None and type(first_exit_reason) is not str:
        raise SnapshotValidationError(
            "first_exit_reason_code: string or None required"
        )
    if type(is_member) is not bool or type(is_quarantined) is not bool:
        raise SnapshotValidationError(
            "funnel evaluation membership flags: bool required"
        )
    evaluation = object.__new__(SecurityEvaluation)
    for field_id, item in (
        ("stock_id", _non_empty(_required(value, "stock_id"), "stock_id")),
        ("futu_code", _non_empty(_required(value, "futu_code"), "futu_code")),
        ("symbol", _non_empty(_required(value, "symbol"), "symbol")),
        ("name", _non_empty(_required(value, "name"), "name")),
        ("field_decisions", decisions),
        ("first_exit_stage", first_exit_stage),
        ("first_exit_reason_code", first_exit_reason),
        ("is_member", is_member),
        ("is_quarantined", is_quarantined),
    ):
        object.__setattr__(evaluation, field_id, item)
    return evaluation


def _funnel_stage_from(value: object) -> FunnelStage:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("funnel stage: mapping required")
    reason_values = _tuple_from(
        _required(value, "reason_counts"), "funnel stage reason_counts"
    )
    reasons: list[tuple[str, int]] = []
    for item in reason_values:
        decoded = _decode_audit(item)
        if type(decoded) is not tuple or len(decoded) != 2:
            raise SnapshotValidationError(
                "funnel stage reason_counts: pairs required"
            )
        reasons.append((str(decoded[0]), int(decoded[1])))
    return FunnelStage(
        stage_order=int(_required(value, "stage_order")),
        stage_id=str(_required(value, "stage_id")),
        input_count=int(_required(value, "input_count")),
        pass_count=int(_required(value, "pass_count")),
        fail_count=int(_required(value, "fail_count")),
        unknown_count=int(_required(value, "unknown_count")),
        reason_counts=tuple(reasons),
        output_count=int(_required(value, "output_count")),
    )


def _funnel_from_payload(value: object) -> UniverseFunnel:
    """Parse frozen Task 8 aggregation without calling Task 8 reconciliation."""

    if not isinstance(value, Mapping):
        raise SnapshotValidationError("funnel: mapping required")
    evaluations = tuple(
        _evaluation_from_payload(item)
        for item in _tuple_from(
            _required(value, "evaluations"), "funnel evaluations"
        )
    )
    stage_payloads = _tuple_from(_required(value, "stages"), "funnel stages")
    if (
        len(stage_payloads) != len(_FUNNEL_STAGE_IDS)
        or any(not isinstance(item, Mapping) for item in stage_payloads)
        or tuple(str(_required(item, "stage_id")) for item in stage_payloads)  # type: ignore[arg-type]
        != _FUNNEL_STAGE_IDS
        or any(
            int(_required(item, "stage_order")) != index  # type: ignore[arg-type]
            for index, item in enumerate(stage_payloads)
        )
    ):
        raise SnapshotValidationError(
            "funnel stages: fixed S0-S10 ID/order contract required"
        )
    stages = tuple(_funnel_stage_from(item) for item in stage_payloads)
    members = tuple(
        _evaluation_from_payload(item)
        for item in _tuple_from(_required(value, "members"), "funnel members")
    )
    if (
        tuple(stage.stage_id for stage in stages) != _FUNNEL_STAGE_IDS
        or any(stage.stage_order != index for index, stage in enumerate(stages))
    ):
        raise SnapshotValidationError(
            "funnel stages: fixed S0-S10 ID/order contract required"
        )
    funnel = object.__new__(UniverseFunnel)
    object.__setattr__(funnel, "evaluations", evaluations)
    object.__setattr__(funnel, "stages", stages)
    object.__setattr__(funnel, "members", members)
    return funnel


def _snapshot_from_payload(value: object) -> UniverseSnapshot:
    if not isinstance(value, Mapping):
        raise SnapshotValidationError("snapshot record: mapping required")
    header = _header_from_payload(_required(value, "header"))
    row_values = _required(value, "rows")
    funnel_value = _required(value, "funnel")
    if not isinstance(row_values, list) or not isinstance(funnel_value, Mapping):
        raise SnapshotValidationError("snapshot rows/funnel required")
    rows = tuple(_row_from_payload(item) for item in row_values)
    funnel = _funnel_from_payload(funnel_value)
    return UniverseSnapshot(header, rows, funnel)


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_create(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


class UniverseSnapshotStore:
    def __init__(self, root: str | Path) -> None:
        if not isinstance(root, (str, Path)) or not str(root):
            raise SnapshotValidationError("root: non-empty path required")
        self._root = Path(root)

    def append(self, snapshot: UniverseSnapshot) -> UniverseSnapshot:
        if type(snapshot) is not UniverseSnapshot:
            raise SnapshotValidationError("snapshot: UniverseSnapshot required")
        # Re-run every binding and hash validation before touching storage.
        snapshot = UniverseSnapshot(snapshot.header, snapshot.rows, snapshot.funnel)
        payload = _canonical_json_bytes(snapshot)
        parsed = json.loads(payload.decode("utf-8"))
        round_trip = _snapshot_from_payload(parsed)
        if _canonical_json_bytes(round_trip) != payload or round_trip != snapshot:
            raise SnapshotValidationError(
                "snapshot: canonical readable round-trip required"
            )
        path = self._root / f"{snapshot.header.universe_snapshot_id}.json"
        try:
            self._root.mkdir(parents=True, exist_ok=True)
            if path.exists():
                existing = self.get(snapshot.header.universe_snapshot_id)
                if _canonical_json_bytes(existing) == payload:
                    return existing
                raise SnapshotConflictError(
                    f"snapshot ID already exists: {snapshot.header.universe_snapshot_id}"
                )
            try:
                _atomic_create(path, payload)
            except FileExistsError:
                existing = self.get(snapshot.header.universe_snapshot_id)
                if _canonical_json_bytes(existing) == payload:
                    return existing
                raise SnapshotConflictError(
                    f"snapshot ID already exists: {snapshot.header.universe_snapshot_id}"
                )
        except SnapshotStoreError:
            raise
        except OSError as error:
            raise SnapshotStoreError(str(error)) from error
        return self.get(snapshot.header.universe_snapshot_id)

    def get(self, snapshot_id: UUID) -> UniverseSnapshot:
        if type(snapshot_id) is not UUID or snapshot_id.int == 0:
            raise SnapshotValidationError("snapshot_id: non-nil UUID required")
        path = self._root / f"{snapshot_id}.json"
        try:
            payload = path.read_bytes()
        except FileNotFoundError as error:
            raise SnapshotNotFoundError(f"snapshot not found: {snapshot_id}") from error
        except OSError as error:
            raise SnapshotStoreError(str(error)) from error
        try:
            parsed = json.loads(payload.decode("utf-8"))
            snapshot = _snapshot_from_payload(parsed)
            if snapshot.header.universe_snapshot_id != snapshot_id:
                raise SnapshotValidationError("snapshot ID/path binding mismatch")
            if _canonical_json_bytes(snapshot) != payload:
                raise SnapshotValidationError("record is not canonical JSON")
            return snapshot
        except (SnapshotValidationError, ValueError, TypeError, UnicodeError) as error:
            raise SnapshotCorruptError(f"corrupt snapshot {snapshot_id}: {error}") from error


__all__ = (
    "SnapshotConflictError",
    "SnapshotCorruptError",
    "SnapshotKind",
    "SnapshotNotFoundError",
    "SnapshotStoreError",
    "SnapshotValidationError",
    "UniverseSnapshot",
    "UniverseSnapshotHeader",
    "UniverseSnapshotRow",
    "UniverseSnapshotStore",
    "build_snapshot",
    "members_sha256",
    "snapshot_content_sha256",
    "snapshot_record_sha256",
)
