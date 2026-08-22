"""Atomic Futu universe-attempt production.

This module deliberately owns provider-status qualification, freshness and
cross-security identity reconciliation.  It does not evaluate a profile,
construct a funnel or persist a snapshot.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from math import isfinite
from types import MappingProxyType
from typing import Any
from zoneinfo import ZoneInfo

from tv_quant.run_manifest import canonical_hash

from .evaluator import NormalizedPrerequisiteDecision, SecurityEvaluationPrerequisites
from .evidence import (
    AttemptStatus,
    Completeness,
    Decision,
    EvidenceProvenance,
    EvidenceReference,
    LiquidityEvidence,
    ListingHistoryEvidence,
    RawIndustryEvidence,
    RawPlateEvidence,
    SecurityClassificationEvidence,
    UniverseSecurityEvidence,
    quantize_usd_cent,
)
from .futu_adapter import FutuProviderAdapter, FutuProviderError, RawApiBatch, RawApiPage
from .security_master import SecurityMasterProvider


_BLOCKERS = frozenset({
    "FUTU_LOGIN_BLOCKER", "FUTU_MARKET_PERMISSION_BLOCKER",
    "FUTU_RATE_LIMIT_RETRY_EXHAUSTED", "FUTU_QUOTA_BLOCKER",
    "FUTU_SCHEMA_BLOCKER", "FUTU_PAGINATION_BLOCKER",
    "UNIVERSE_IDENTITY_BLOCKER", "UNIVERSE_FRESHNESS_BLOCKER",
    "UNIVERSE_INCOMPLETE_BLOCKER", "CLASSIFICATION_EVIDENCE_BLOCKER",
    "LIQUIDITY_EVIDENCE_CONFLICT", "LISTING_HISTORY_CONFLICT",
})
_ACTIVE_DECISIONS = frozenset({Decision.PASS, Decision.FAIL})
_NEW_YORK = ZoneInfo("America/New_York")
_QUALIFIED_ACTIVE_SDK_VERSION = "10.10.7008"
_QUALIFIED_OPEND_VERSION = "1009"
PROVIDER_OR_ACCOUNT_LEVEL_CURRENT_QUOTE_RIGHT_AUTHORITY = "NOT_YET_QUALIFIED"
FORMAL_FRESHNESS_AUTHORITY = "NOT_QUALIFIED"
CURRENT_QUOTE_RIGHT_AUTHORITY_NOT_QUALIFIED = "CURRENT_QUOTE_RIGHT_AUTHORITY_NOT_QUALIFIED"


def _non_empty(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field}: non-empty string required")
    return value


def _utc_datetime(value: object, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field}: UTC datetime required")
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError(f"{field}: UTC datetime required")
    return value


def _runtime_window(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("runtime_evidence_window_seconds: finite nonnegative number required")
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0:
        raise ValueError("runtime_evidence_window_seconds: finite nonnegative number required")
    return normalized


def _references(values: Sequence[EvidenceReference], field: str) -> tuple[EvidenceReference, ...]:
    result = tuple(values)
    if any(type(item) is not EvidenceReference for item in result):
        raise ValueError(f"{field}: EvidenceReference values required")
    return tuple(sorted(result, key=lambda item: (item.source_id, item.source_locator, item.source_record_sha256)))


def _reasons(values: Sequence[str]) -> tuple[str, ...]:
    result = tuple(sorted(set(values)))
    if any(item not in _BLOCKERS for item in result):
        raise ValueError("reason_codes: stable blocker required")
    return result


def _mapping_payload(mapping: "QualifiedActiveStatusMapping") -> dict[str, object]:
    return {
        "provider": mapping.provider,
        "provider_sdk_version": mapping.provider_sdk_version,
        "opend_server_version": mapping.opend_server_version,
        "mapping_version": mapping.mapping_version,
        "entries": [
            {"raw_value": item.raw_value, "decision": item.decision.value, "reason_code": item.reason_code}
            for item in mapping.entries
        ],
        "qualified_at_utc": mapping.qualified_at_utc.isoformat(),
        "qualification_references": [
            {"source_id": ref.source_id, "source_locator": ref.source_locator, "source_record_sha256": ref.source_record_sha256}
            for ref in mapping.qualification_references
        ],
    }


def _market_state_contract_payload(contract: "QualifiedMarketStateConsistencyContract") -> dict[str, object]:
    return {
        "provider": contract.provider,
        "provider_sdk_version": contract.provider_sdk_version,
        "opend_server_version": contract.opend_server_version,
        "mapping_version": contract.mapping_version,
        "qualified_at_utc": contract.qualified_at_utc.isoformat(),
        "qualification_references": [
            {"source_id": ref.source_id, "source_locator": ref.source_locator, "source_record_sha256": ref.source_record_sha256}
            for ref in contract.qualification_references
        ],
        "qualified_relationships": [
            {
                "raw_market_state": relationship.raw_market_state,
                "calendar_relationship": relationship.calendar_relationship,
            }
            for relationship in contract.qualified_relationships
        ],
    }


@dataclass(frozen=True, slots=True)
class ActiveStatusMappingEntry:
    raw_value: str
    decision: Decision
    reason_code: str

    def __post_init__(self) -> None:
        _non_empty(self.raw_value, "raw_value")
        if type(self.decision) is not Decision or self.decision not in _ACTIVE_DECISIONS:
            raise ValueError("decision: PASS or FAIL required")
        _non_empty(self.reason_code, "reason_code")


@dataclass(frozen=True, slots=True)
class QualifiedActiveStatusMapping:
    provider: str
    provider_sdk_version: str
    opend_server_version: str
    mapping_version: str
    entries: tuple[ActiveStatusMappingEntry, ...]
    qualified_at_utc: datetime
    qualification_references: tuple[EvidenceReference, ...]
    active_status_mapping_sha256: str = ""

    def __post_init__(self) -> None:
        for field in ("provider", "provider_sdk_version", "opend_server_version", "mapping_version"):
            _non_empty(getattr(self, field), field)
        if self.provider_sdk_version.strip().lower() in {"unknown", "unqualified", "n/a"}:
            raise ValueError("provider_sdk_version: concrete qualified version required")
        if self.opend_server_version.strip().lower() in {"unknown", "unqualified", "n/a"}:
            raise ValueError("opend_server_version: concrete qualified version required")
        if self.provider != "FUTU":
            raise ValueError("provider: FUTU required")
        if self.provider_sdk_version != _QUALIFIED_ACTIVE_SDK_VERSION:
            raise ValueError(f"provider_sdk_version: {_QUALIFIED_ACTIVE_SDK_VERSION} required")
        if self.opend_server_version != _QUALIFIED_OPEND_VERSION:
            raise ValueError(f"opend_server_version: {_QUALIFIED_OPEND_VERSION} required")
        _utc_datetime(self.qualified_at_utc, "qualified_at_utc")
        entries = tuple(self.entries)
        if not entries or any(type(item) is not ActiveStatusMappingEntry for item in entries):
            raise ValueError("entries: non-empty ActiveStatusMappingEntry values required")
        entries = tuple(sorted(entries, key=lambda item: item.raw_value))
        if len({item.raw_value for item in entries}) != len(entries):
            raise ValueError("entries: raw_value values must be unique")
        if any(item.raw_value == "*" for item in entries):
            raise ValueError("entries: wildcard mapping forbidden")
        if len(entries) != 1 or entries[0].raw_value != "NORMAL" or entries[0].decision is not Decision.PASS:
            raise ValueError("entries: only NORMAL PASS is qualified")
        references = _references(self.qualification_references, "qualification_references")
        if not references:
            raise ValueError("qualification_references: qualification evidence required")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "qualification_references", references)
        calculated = canonical_hash(_mapping_payload(self))
        if self.active_status_mapping_sha256 and self.active_status_mapping_sha256 != calculated:
            raise ValueError("active_status_mapping_sha256: mapping tamper detected")
        object.__setattr__(self, "active_status_mapping_sha256", calculated)

    @property
    def canonical_sha256(self) -> str:
        return self.active_status_mapping_sha256


@dataclass(frozen=True, slots=True)
class QualifiedMarketStateRelationship:
    raw_market_state: str
    calendar_relationship: str

    def __post_init__(self) -> None:
        _non_empty(self.raw_market_state, "raw_market_state")
        _non_empty(self.calendar_relationship, "calendar_relationship")


@dataclass(frozen=True, slots=True)
class QualifiedMarketStateConsistencyContract:
    provider: str
    provider_sdk_version: str
    opend_server_version: str
    mapping_version: str
    qualified_at_utc: datetime
    qualification_references: tuple[EvidenceReference, ...]
    qualified_relationships: tuple[QualifiedMarketStateRelationship, ...]
    market_state_consistency_sha256: str = ""

    def __post_init__(self) -> None:
        for field in ("provider", "provider_sdk_version", "opend_server_version", "mapping_version"):
            _non_empty(getattr(self, field), field)
        if self.provider != "FUTU":
            raise ValueError("provider: FUTU required")
        if self.provider_sdk_version != _QUALIFIED_ACTIVE_SDK_VERSION:
            raise ValueError(f"provider_sdk_version: {_QUALIFIED_ACTIVE_SDK_VERSION} required")
        if self.opend_server_version != _QUALIFIED_OPEND_VERSION:
            raise ValueError(f"opend_server_version: {_QUALIFIED_OPEND_VERSION} required")
        _utc_datetime(self.qualified_at_utc, "qualified_at_utc")
        references = _references(self.qualification_references, "qualification_references")
        if not references:
            raise ValueError("qualification_references: qualification evidence required")
        relationships = tuple(sorted(
            self.qualified_relationships,
            key=lambda item: (item.raw_market_state, item.calendar_relationship),
        ))
        if not relationships or any(type(item) is not QualifiedMarketStateRelationship for item in relationships):
            raise ValueError("qualified_relationships: values required")
        if len({(item.raw_market_state, item.calendar_relationship) for item in relationships}) != len(relationships):
            raise ValueError("qualified_relationships: duplicate relationship")
        if relationships != (QualifiedMarketStateRelationship("AFTER_HOURS_END", "XNYS_NON_SESSION"),):
            raise ValueError("qualified_relationships: only observed AFTER_HOURS_END XNYS_NON_SESSION is qualified")
        object.__setattr__(self, "qualification_references", references)
        object.__setattr__(self, "qualified_relationships", relationships)
        calculated = canonical_hash(_market_state_contract_payload(self))
        if self.market_state_consistency_sha256 and self.market_state_consistency_sha256 != calculated:
            raise ValueError("market_state_consistency_sha256: contract tamper detected")
        object.__setattr__(self, "market_state_consistency_sha256", calculated)

    @property
    def canonical_sha256(self) -> str:
        return self.market_state_consistency_sha256


@dataclass(frozen=True, slots=True)
class GatewayPreflight:
    provider: str
    provider_sdk_version: str
    opend_server_version: str
    as_of_session: date
    observed_at_utc: datetime
    provider_update_time: datetime | None
    market_data_delay_class: str
    formal_ready: bool
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty(self.provider, "provider")
        _non_empty(self.provider_sdk_version, "provider_sdk_version")
        _non_empty(self.opend_server_version, "opend_server_version")
        if type(self.as_of_session) is not date:
            raise ValueError("as_of_session: date required")
        _utc_datetime(self.observed_at_utc, "observed_at_utc")
        if self.provider_update_time is not None:
            _utc_datetime(self.provider_update_time, "provider_update_time")
        _non_empty(self.market_data_delay_class, "market_data_delay_class")
        if type(self.formal_ready) is not bool:
            raise ValueError("formal_ready: bool required")
        object.__setattr__(self, "reason_codes", _reasons(self.reason_codes))


@dataclass(frozen=True, slots=True)
class ApiBatchRecord:
    endpoint: str
    batch_index: int
    request_hash: str
    response_hash: str
    acquired_at_utc: datetime
    page_index: int | None = None

    def __post_init__(self) -> None:
        _non_empty(self.endpoint, "endpoint")
        if type(self.batch_index) is not int or self.batch_index < 1:
            raise ValueError("batch_index: positive integer required")
        if self.page_index is not None and (type(self.page_index) is not int or self.page_index < 1):
            raise ValueError("page_index: positive integer or None required")
        for field in ("request_hash", "response_hash"):
            value = getattr(self, field)
            if type(value) is not str or len(value) != 64:
                raise ValueError(f"{field}: SHA-256 required")
        _utc_datetime(self.acquired_at_utc, "acquired_at_utc")


@dataclass(frozen=True, slots=True)
class IdentityLedgerEntry:
    stock_id: str
    futu_code: str
    decision: Decision
    reason_code: str
    competing_stock_ids: tuple[str, ...]
    competing_futu_codes: tuple[str, ...]
    evidence_references: tuple[EvidenceReference, ...]
    reconciliation_completed: bool = False

    def __post_init__(self) -> None:
        _non_empty(self.stock_id, "stock_id")
        _non_empty(self.futu_code, "futu_code")
        if type(self.decision) is not Decision or self.decision not in {Decision.PASS, Decision.UNKNOWN}:
            raise ValueError("decision: PASS or UNKNOWN required")
        if type(self.reconciliation_completed) is not bool:
            raise ValueError("reconciliation_completed: bool required")
        if self.decision is Decision.PASS and not self.reconciliation_completed:
            raise ValueError("identity PASS requires explicit reconciliation completion")
        _non_empty(self.reason_code, "reason_code")
        stock_ids = tuple(sorted(set(self.competing_stock_ids)))
        codes = tuple(sorted(set(self.competing_futu_codes)))
        if not stock_ids or not codes:
            raise ValueError("identity ledger: competing identity values required")
        object.__setattr__(self, "competing_stock_ids", stock_ids)
        object.__setattr__(self, "competing_futu_codes", codes)
        object.__setattr__(self, "evidence_references", _references(self.evidence_references, "evidence_references"))


def _prerequisite_payload(item: SecurityEvaluationPrerequisites) -> dict[str, object]:
    def decision(value: NormalizedPrerequisiteDecision | None) -> object:
        if value is None:
            return None
        return {
            "decision": value.decision.value,
            "reason_code": value.reason_code,
            "evidence_references": [
                {"source_id": ref.source_id, "source_locator": ref.source_locator, "source_record_sha256": ref.source_record_sha256}
                for ref in value.evidence_references
            ],
        }
    return {"stock_id": item.stock_id, "futu_code": item.futu_code, "active_status": decision(item.active_status), "identity": decision(item.identity)}


def prerequisites_sha256(prerequisites: Sequence[SecurityEvaluationPrerequisites]) -> str:
    values = tuple(prerequisites)
    if any(type(item) is not SecurityEvaluationPrerequisites for item in values):
        raise ValueError("prerequisites: SecurityEvaluationPrerequisites values required")
    ordered = tuple(sorted(values, key=lambda item: (item.stock_id, item.futu_code)))
    if len({(item.stock_id, item.futu_code) for item in ordered}) != len(ordered):
        raise ValueError("prerequisites: duplicate composite key")
    return canonical_hash({"prerequisites": [_prerequisite_payload(item) for item in ordered]})


@dataclass(frozen=True, slots=True)
class GatewayAttempt:
    attempt_id: str
    as_of_session: date
    observed_at_utc: datetime
    provider_update_time: datetime | None
    runtime_evidence_window_seconds: float
    market_data_delay_class: str
    market_state_consistency_contract: QualifiedMarketStateConsistencyContract
    active_status_mapping: QualifiedActiveStatusMapping
    prerequisites_sha256: str
    preflight: GatewayPreflight
    evidence: tuple[UniverseSecurityEvidence, ...]
    prerequisites: tuple[SecurityEvaluationPrerequisites, ...]
    batches: tuple[ApiBatchRecord, ...]
    identity_ledger: tuple[IdentityLedgerEntry, ...]
    attempt_status: AttemptStatus
    completeness: Completeness
    reason_codes: tuple[str, ...]
    realtime_capability_probes: tuple[RawApiBatch, ...] = ()

    def __post_init__(self) -> None:
        _non_empty(self.attempt_id, "attempt_id")
        if type(self.as_of_session) is not date:
            raise ValueError("as_of_session: date required")
        _utc_datetime(self.observed_at_utc, "observed_at_utc")
        if self.provider_update_time is not None:
            _utc_datetime(self.provider_update_time, "provider_update_time")
        _runtime_window(self.runtime_evidence_window_seconds)
        _non_empty(self.market_data_delay_class, "market_data_delay_class")
        if (
            type(self.active_status_mapping) is not QualifiedActiveStatusMapping
            or type(self.market_state_consistency_contract) is not QualifiedMarketStateConsistencyContract
            or type(self.preflight) is not GatewayPreflight
        ):
            raise ValueError("qualified mappings/contracts and preflight required")
        if type(self.prerequisites_sha256) is not str or len(self.prerequisites_sha256) != 64:
            raise ValueError("prerequisites_sha256: SHA-256 required")
        evidence = tuple(sorted(self.evidence, key=lambda item: (item.stock_id, item.futu_code)))
        prerequisites = tuple(sorted(self.prerequisites, key=lambda item: (item.stock_id, item.futu_code)))
        if any(type(item) is not UniverseSecurityEvidence for item in evidence) or any(type(item) is not SecurityEvaluationPrerequisites for item in prerequisites):
            raise ValueError("evidence and prerequisites types required")
        if len({(item.stock_id, item.futu_code) for item in evidence}) != len(evidence):
            raise ValueError("evidence: duplicate composite key")
        if len({(item.stock_id, item.futu_code) for item in prerequisites}) != len(prerequisites):
            raise ValueError("prerequisites: duplicate composite key")
        if prerequisites_sha256(prerequisites) != self.prerequisites_sha256:
            raise ValueError("prerequisites_sha256: mismatched content")
        if self.attempt_status is AttemptStatus.SUCCEEDED or self.completeness is Completeness.COMPLETE:
            if self.attempt_status is not AttemptStatus.SUCCEEDED or self.completeness is not Completeness.COMPLETE:
                raise ValueError("complete attempt must succeed")
            if {(item.stock_id, item.futu_code) for item in evidence} != {(item.stock_id, item.futu_code) for item in prerequisites}:
                raise ValueError("evidence/prerequisites: composite keys must match")
        if type(self.attempt_status) is not AttemptStatus or type(self.completeness) is not Completeness:
            raise ValueError("attempt status and completeness required")
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "prerequisites", prerequisites)
        object.__setattr__(self, "batches", tuple(self.batches))
        probes = tuple(self.realtime_capability_probes)
        if any(type(item) is not RawApiBatch for item in probes):
            raise ValueError("realtime_capability_probes: RawApiBatch values required")
        for probe in probes:
            request = probe.raw_request
            if (
                probe.endpoint != "realtime_quote_capability_probe"
                or not isinstance(request, Mapping)
                or type(request.get("code")) is not str
                or not request["code"].strip()
                or request.get("subtype") != "QUOTE"
                or request.get("subscribe_push") is not False
            ):
                raise ValueError(
                    "realtime_capability_probes: realtime_quote_capability_probe "
                    "with one code, subtype QUOTE, and subscribe_push=False required"
                )
        object.__setattr__(self, "realtime_capability_probes", probes)
        object.__setattr__(self, "identity_ledger", tuple(sorted(self.identity_ledger, key=lambda item: (item.stock_id, item.futu_code))))
        object.__setattr__(self, "reason_codes", _reasons(self.reason_codes))


def _records(value: object) -> tuple[Mapping[str, Any], ...]:
    if isinstance(value, Mapping):
        for key in ("rows", "data", "__table_records__"):
            if key in value:
                return _records(value[key])
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _raw_rows(value: object) -> tuple[object, ...]:
    """Return a response's raw table rows without silently discarding malformed rows."""
    if isinstance(value, Mapping):
        for key in ("rows", "data", "__table_records__"):
            if key in value:
                return _raw_rows(value[key])
        return ()
    if isinstance(value, (tuple, list)):
        return tuple(value)
    return ()


def _field(row: Mapping[str, Any] | None, *names: str) -> object | None:
    if row is None:
        return None
    folded = {str(key).lower(): value for key, value in row.items()}
    for name in names:
        if name.lower() in folded:
            return folded[name.lower()]
    return None


def _has_field(row: Mapping[str, Any] | None, name: str) -> bool:
    return row is not None and name.lower() in {str(key).lower() for key in row}


def _text(value: object) -> str | None:
    if isinstance(value, Mapping) and set(value) == {"__float_repr__"}:
        value = value["__float_repr__"]
    return value.strip() if type(value) is str and value.strip() else None


def _decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    text = _text(value)
    if text is None:
        return None
    try:
        return quantize_usd_cent(text, field_id=field)
    except ValueError:
        return None


def _integer(value: object) -> int | None:
    if isinstance(value, Mapping) and set(value) == {"__float_repr__"}:
        value = value["__float_repr__"]
    if type(value) is int and not isinstance(value, bool) and value >= 0:
        return value
    if type(value) is str and value.isdecimal():
        return int(value)
    if type(value) is str:
        try:
            parsed = Decimal(value)
        except Exception:
            return None
        if parsed.is_finite() and parsed >= 0 and parsed == parsed.to_integral_value():
            return int(parsed)
    return None


def _parse_us_update_time(value: object) -> datetime | None:
    """Parse the documented offset-less US snapshot wall time fail-closed."""
    if type(value) is not str:
        return None
    try:
        local = datetime.strptime(value, "%Y-%m-%d %H:%M:%S.%f") if "." in value else datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        aware = local.replace(tzinfo=_NEW_YORK, fold=fold)
        utc = aware.astimezone(UTC)
        if utc.astimezone(_NEW_YORK).replace(tzinfo=None) == local:
            candidates[utc] = aware
    return next(iter(candidates)) if len(candidates) == 1 else None


def _blocker(error: Exception) -> str:
    message = str(error).upper()
    if "FUTU_RATE_LIMIT_RETRY_EXHAUSTED" in message:
        return "FUTU_RATE_LIMIT_RETRY_EXHAUSTED"
    if "FUTU_QUOTA_BLOCKER" in message or "QUOTA EXCEEDED" in message:
        return "FUTU_QUOTA_BLOCKER"
    if "FUTU_MARKET_PERMISSION_BLOCKER" in message or "PERMISSION DENIED" in message:
        return "FUTU_MARKET_PERMISSION_BLOCKER"
    if "FUTU_LOGIN_BLOCKER" in message or "LOGIN REQUIRED" in message:
        return "FUTU_LOGIN_BLOCKER"
    if "FUTU_PAGINATION_BLOCKER" in message:
        return "FUTU_PAGINATION_BLOCKER"
    return "FUTU_SCHEMA_BLOCKER"


class FutuUniverseGateway:
    """Compose Task 9 raw acquisition into one immutable, fail-closed attempt."""

    def __init__(self, *, sdk: Any | None = None, host: str = "127.0.0.1", port: int = 11111, clock: Callable[[], datetime], sleep: Callable[[float], None]) -> None:
        if sdk is None:
            try:
                import futu as sdk  # type: ignore[import-not-found]
            except ImportError as error:
                raise RuntimeError("FUTU_LOGIN_BLOCKER: Futu SDK unavailable") from error
        _non_empty(host, "host")
        if type(port) is not int or port < 1:
            raise ValueError("port: positive integer required")
        self._sdk, self._host, self._port, self._clock, self._sleep = sdk, host, port, clock, sleep

    def normalized_active_status(self, *, delisting: object, suspension: object, raw_status: object, evidence_references: Sequence[EvidenceReference], mapping: QualifiedActiveStatusMapping, provider: str, provider_sdk_version: str, opend_server_version: str) -> NormalizedPrerequisiteDecision:
        references = _references(evidence_references, "evidence_references")
        if delisting is True:
            return NormalizedPrerequisiteDecision(Decision.FAIL, "DELISTED", references)
        if suspension is True:
            return NormalizedPrerequisiteDecision(Decision.FAIL, "SUSPENDED_AS_OF_SNAPSHOT", references)
        if type(delisting) is not bool or type(suspension) is not bool:
            return NormalizedPrerequisiteDecision(Decision.UNKNOWN, "ACTIVE_STATUS_UNKNOWN", references)
        if (
            mapping.provider != provider
            or mapping.provider_sdk_version != provider_sdk_version
            or mapping.opend_server_version != opend_server_version
        ):
            return NormalizedPrerequisiteDecision(Decision.UNKNOWN, "ACTIVE_STATUS_UNKNOWN", references)
        status = _text(raw_status)
        if status is None:
            return NormalizedPrerequisiteDecision(Decision.UNKNOWN, "ACTIVE_STATUS_UNKNOWN", references)
        entry = next((item for item in mapping.entries if item.raw_value == status), None)
        if entry is None:
            return NormalizedPrerequisiteDecision(Decision.UNKNOWN, "ACTIVE_STATUS_UNKNOWN", references)
        return NormalizedPrerequisiteDecision(entry.decision, entry.reason_code, references)

    def _adapter(self) -> FutuProviderAdapter:
        gateway = self

        class _EndpointBoundSdk:
            def __getattr__(self, name: str) -> Any:
                return getattr(gateway._sdk, name)

            def OpenQuoteContext(self) -> Any:
                try:
                    return gateway._sdk.OpenQuoteContext(host=gateway._host, port=gateway._port)
                except TypeError:
                    # Task 9 test doubles intentionally expose a no-argument factory.
                    return gateway._sdk.OpenQuoteContext()

        return FutuProviderAdapter(sdk=_EndpointBoundSdk(), clock=self._clock, sleep=self._sleep)

    @staticmethod
    def _runtime_versions(runtime_batches: Sequence[RawApiBatch]) -> tuple[str, str]:
        by_endpoint: dict[str, list[RawApiBatch]] = defaultdict(list)
        for batch in runtime_batches:
            by_endpoint[batch.endpoint].append(batch)
        if set(by_endpoint) != {"runtime_sdk_version", "global_state", "qot_right_capture"} or any(len(items) != 1 for items in by_endpoint.values()):
            raise FutuProviderError("FUTU_SCHEMA_BLOCKER: runtime evidence endpoints malformed")
        sdk_version = _text(_field(by_endpoint["runtime_sdk_version"][0].raw_response, "sdk_version"))
        opend_version = _text(_field(by_endpoint["global_state"][0].raw_response, "server_ver"))
        events = _field(by_endpoint["qot_right_capture"][0].raw_response, "events")
        if (
            sdk_version is None
            or opend_version is None
            or not isinstance(events, (tuple, list))
            or any(
                not isinstance(event, Mapping)
                or not _has_field(event, "notify_type")
                or not _has_field(event, "sub_type")
                or not isinstance(_field(event, "msg"), Mapping)
                or not _has_field(_field(event, "msg"), "us_qot_right")
                for event in events
            )
        ):
            raise FutuProviderError("FUTU_SCHEMA_BLOCKER: runtime evidence shape malformed")
        return sdk_version, opend_version

    def _preflight(
        self,
        *,
        as_of_session: date,
        observed_at_utc: datetime,
        provider_sdk_version: str,
        opend_server_version: str,
        snapshots: Sequence[Mapping[str, Any]],
        market_states: Sequence[Mapping[str, Any]],
        market_state_consistency_contract: QualifiedMarketStateConsistencyContract,
    ) -> GatewayPreflight:
        update_values = {_parse_us_update_time(_field(row, "update_time")) for row in snapshots}
        reasons: list[str] = []
        provider_update_time = next(iter(update_values)) if len(update_values) == 1 else None
        delay = "UNKNOWN"
        calendar_relationship: str | None = None
        try:
            import exchange_calendars as exchange_calendars
            calendar = exchange_calendars.get_calendar("XNYS")
            sessions = [
                candidate
                for candidate in (observed_at_utc.date().fromordinal(observed_at_utc.date().toordinal() - offset) for offset in range(10))
                if calendar.is_session(candidate) and calendar.session_close(candidate) <= observed_at_utc
            ]
            latest = sessions[0] if sessions else None
            session_close = calendar.session_close(as_of_session) if calendar.is_session(as_of_session) else None
            calendar_relationship = (
                "XNYS_SESSION_OPEN"
                if calendar.is_open_on_minute(observed_at_utc)
                else "XNYS_NON_SESSION"
            )
        except Exception:
            latest, session_close = None, None
        contract_matches_runtime = (
            market_state_consistency_contract.provider == "FUTU"
            and market_state_consistency_contract.provider_sdk_version == provider_sdk_version
            and market_state_consistency_contract.opend_server_version == opend_server_version
        )
        qualified_relationships = {
            (item.raw_market_state, item.calendar_relationship)
            for item in market_state_consistency_contract.qualified_relationships
        }
        raw_states = tuple(_text(_field(row, "market_state")) for row in market_states)
        market_states_qualified = (
            contract_matches_runtime
            and calendar_relationship is not None
            and bool(raw_states)
            and all(state is not None and (state, calendar_relationship) in qualified_relationships for state in raw_states)
        )
        if (
            as_of_session != latest
            or session_close is None
            or provider_update_time is None
            or provider_update_time < session_close
            or provider_update_time > observed_at_utc
            or not market_states_qualified
            # Scalable current quote-right authority is intentionally not yet qualified.
            or PROVIDER_OR_ACCOUNT_LEVEL_CURRENT_QUOTE_RIGHT_AUTHORITY != "QUALIFIED"
            or FORMAL_FRESHNESS_AUTHORITY != "QUALIFIED"
        ):
            reasons.append("UNIVERSE_FRESHNESS_BLOCKER")
        return GatewayPreflight("FUTU", provider_sdk_version, opend_server_version, as_of_session, observed_at_utc, provider_update_time, delay, not reasons, tuple(reasons))

    @staticmethod
    def _batch_records(*collections: Sequence[RawApiBatch] | Sequence[RawApiPage]) -> tuple[ApiBatchRecord, ...]:
        records: list[ApiBatchRecord] = []
        for collection in collections:
            for item in collection:
                if type(item) is RawApiBatch:
                    records.append(ApiBatchRecord(item.endpoint, item.batch_index, item.request_hash, item.response_hash, item.acquired_at_utc))
                elif type(item) is RawApiPage:
                    records.append(ApiBatchRecord(item.endpoint, item.page_index, item.request_hash, item.response_hash, item.acquired_at_utc, item.page_index))
                else:
                    raise ValueError("Task 9 raw batch/page required")
        return tuple(sorted(records, key=lambda item: (item.endpoint, item.batch_index, item.page_index or 0)))

    @staticmethod
    def _reference(source: str, locator: str, record_hash: str) -> EvidenceReference:
        return EvidenceReference(source, locator, record_hash)

    @staticmethod
    def _attempt_id(
        *,
        as_of_session: date,
        observed_at_utc: datetime,
        mapping: QualifiedActiveStatusMapping,
        market_state_contract: QualifiedMarketStateConsistencyContract,
        runtime_evidence_window_seconds: float,
        reasons: Sequence[str],
        prerequisites_hash: str,
        batches: Sequence[ApiBatchRecord],
        realtime_capability_probes: Sequence[RawApiBatch] = (),
    ) -> str:
        return canonical_hash({
            "as_of_session": as_of_session.isoformat(),
            "observed_at_utc": observed_at_utc.isoformat(),
            "mapping": mapping.active_status_mapping_sha256,
            "market_state_contract": market_state_contract.canonical_sha256,
            "runtime_evidence_window_seconds": repr(runtime_evidence_window_seconds),
            "reasons": list(reasons),
            "prerequisites": prerequisites_hash,
            "batches": [item.response_hash for item in batches],
            "realtime_capability_probes": [
                {
                    "endpoint": item.endpoint,
                    "batch_index": item.batch_index,
                    "request_hash": item.request_hash,
                    "response_hash": item.response_hash,
                    "acquired_at_utc": item.acquired_at_utc.isoformat(),
                }
                for item in realtime_capability_probes
            ],
        })

    def _failed_attempt(self, *, as_of_session: date, observed_at_utc: datetime, mapping: QualifiedActiveStatusMapping, market_state_contract: QualifiedMarketStateConsistencyContract, provider_sdk_version: str, opend_server_version: str, runtime_evidence_window_seconds: float, reason_codes: Sequence[str], batches: Sequence[ApiBatchRecord] = (), evidence: Sequence[UniverseSecurityEvidence] = (), prerequisites: Sequence[SecurityEvaluationPrerequisites] = (), ledger: Sequence[IdentityLedgerEntry] = (), preflight: GatewayPreflight | None = None, realtime_capability_probes: Sequence[RawApiBatch] = ()) -> GatewayAttempt:
        supplied_reasons = tuple(reason_codes)
        reasons = _reasons(supplied_reasons if "UNIVERSE_FRESHNESS_BLOCKER" in supplied_reasons else supplied_reasons + ("UNIVERSE_INCOMPLETE_BLOCKER",))
        prerequisite_hash = prerequisites_sha256(prerequisites)
        if preflight is None:
            preflight = GatewayPreflight("FUTU", provider_sdk_version, opend_server_version, as_of_session, observed_at_utc, None, "UNKNOWN", False, reasons)
        else:
            preflight = GatewayPreflight(preflight.provider, preflight.provider_sdk_version, preflight.opend_server_version, preflight.as_of_session, preflight.observed_at_utc, preflight.provider_update_time, preflight.market_data_delay_class, False, _reasons(preflight.reason_codes + reasons))
        attempt_id = self._attempt_id(as_of_session=as_of_session, observed_at_utc=observed_at_utc, mapping=mapping, market_state_contract=market_state_contract, runtime_evidence_window_seconds=runtime_evidence_window_seconds, reasons=reasons, prerequisites_hash=prerequisite_hash, batches=batches, realtime_capability_probes=realtime_capability_probes)
        return GatewayAttempt(attempt_id=attempt_id, as_of_session=as_of_session, observed_at_utc=observed_at_utc, provider_update_time=preflight.provider_update_time, runtime_evidence_window_seconds=runtime_evidence_window_seconds, market_data_delay_class=preflight.market_data_delay_class, market_state_consistency_contract=market_state_contract, active_status_mapping=mapping, prerequisites_sha256=prerequisite_hash, preflight=preflight, evidence=tuple(evidence), prerequisites=tuple(prerequisites), batches=tuple(batches), identity_ledger=tuple(ledger), attempt_status=AttemptStatus.FAILED, completeness=Completeness.INCOMPLETE, reason_codes=reasons, realtime_capability_probes=tuple(realtime_capability_probes))

    def collect(self, *, as_of_session: date, observed_at_utc: datetime, classification_provider: SecurityMasterProvider, active_status_mapping: QualifiedActiveStatusMapping, market_state_consistency_contract: QualifiedMarketStateConsistencyContract, runtime_evidence_window_seconds: float) -> GatewayAttempt:
        if type(as_of_session) is not date:
            raise ValueError("as_of_session: date required")
        _utc_datetime(observed_at_utc, "observed_at_utc")
        if type(active_status_mapping) is not QualifiedActiveStatusMapping:
            raise ValueError("active_status_mapping: QualifiedActiveStatusMapping required")
        if type(market_state_consistency_contract) is not QualifiedMarketStateConsistencyContract:
            raise ValueError("market_state_consistency_contract: QualifiedMarketStateConsistencyContract required")
        window = _runtime_window(runtime_evidence_window_seconds)
        adapter = self._adapter()
        failure_context: dict[str, object] = {}
        try:
            runtime = adapter.collect_runtime_evidence(notification_window_seconds=window)
            runtime_batches = self._batch_records(runtime)
            failure_context["batches"] = runtime_batches
            provider_sdk_version, opend_server_version = self._runtime_versions(runtime)
            return self._collect_impl(as_of_session=as_of_session, observed_at_utc=observed_at_utc, classification_provider=classification_provider, active_status_mapping=active_status_mapping, market_state_consistency_contract=market_state_consistency_contract, runtime_evidence_window_seconds=window, provider_sdk_version=provider_sdk_version, opend_server_version=opend_server_version, adapter=adapter, runtime=runtime, failure_context=failure_context)
        except Exception as error:
            return self._failed_attempt(as_of_session=as_of_session, observed_at_utc=observed_at_utc, mapping=active_status_mapping, market_state_contract=market_state_consistency_contract, provider_sdk_version="unavailable", opend_server_version="unavailable", runtime_evidence_window_seconds=window, reason_codes=(_blocker(error),), batches=failure_context.get("batches", ()), evidence=failure_context.get("evidence", ()), prerequisites=failure_context.get("prerequisites", ()), ledger=failure_context.get("ledger", ()), preflight=failure_context.get("preflight"))  # type: ignore[arg-type]

    def _collect_impl(self, *, as_of_session: date, observed_at_utc: datetime, classification_provider: SecurityMasterProvider, active_status_mapping: QualifiedActiveStatusMapping, market_state_consistency_contract: QualifiedMarketStateConsistencyContract, runtime_evidence_window_seconds: float, provider_sdk_version: str, opend_server_version: str, adapter: FutuProviderAdapter, runtime: Sequence[RawApiBatch], failure_context: dict[str, object]) -> GatewayAttempt:
        try:
            discovery = adapter.discover_cash_securities()
            discovery_rows = tuple(row for batch in discovery for row in _records(batch.raw_response))
            codes = tuple(sorted({_text(_field(row, "code", "futu_code")) for row in discovery_rows if _text(_field(row, "code", "futu_code"))}))
            if not codes:
                raise FutuProviderError("FUTU_SCHEMA_BLOCKER: discovery returned no candidates")
            discovery_by_code: dict[str, set[str]] = defaultdict(set)
            discovery_keys: list[tuple[str, str]] = []
            for row in discovery_rows:
                code, stock_id = _text(_field(row, "code", "futu_code")), _text(_field(row, "stock_id", "id"))
                if code is not None and stock_id is not None:
                    discovery_by_code[code].add(stock_id)
                    discovery_keys.append((stock_id, code))
            discovery_batches = self._batch_records(runtime, discovery)
            if len(set(discovery_keys)) != len(discovery_keys):
                return self._failed_attempt(as_of_session=as_of_session, observed_at_utc=observed_at_utc, mapping=active_status_mapping, market_state_contract=market_state_consistency_contract, provider_sdk_version=provider_sdk_version, opend_server_version=opend_server_version, runtime_evidence_window_seconds=runtime_evidence_window_seconds, reason_codes=("FUTU_SCHEMA_BLOCKER",), batches=discovery_batches)
            if any(len(stock_ids) > 1 for stock_ids in discovery_by_code.values()):
                ledger: list[IdentityLedgerEntry] = []
                for row in discovery_rows:
                    code, stock_id = _text(_field(row, "code", "futu_code")), _text(_field(row, "stock_id", "id"))
                    if code is None or stock_id is None:
                        continue
                    batch = next(batch for batch in discovery if row in _records(batch.raw_response))
                    ledger.append(IdentityLedgerEntry(stock_id, code, Decision.UNKNOWN, "UNIVERSE_IDENTITY_BLOCKER", tuple(discovery_by_code[code]), (code,), (self._reference("futu-discovery", f"futu://discovery/{code}", batch.response_hash),), reconciliation_completed=False))
                return self._failed_attempt(as_of_session=as_of_session, observed_at_utc=observed_at_utc, mapping=active_status_mapping, market_state_contract=market_state_consistency_contract, provider_sdk_version=provider_sdk_version, opend_server_version=opend_server_version, runtime_evidence_window_seconds=runtime_evidence_window_seconds, reason_codes=("UNIVERSE_IDENTITY_BLOCKER",), batches=discovery_batches, ledger=ledger)
            screens = adapter.screen_all_pages()
            snapshots = adapter.market_snapshots(codes)
            market_states = adapter.market_states(codes)
            plates = adapter.owner_plates(codes)
        except Exception as error:
            return self._failed_attempt(as_of_session=as_of_session, observed_at_utc=observed_at_utc, mapping=active_status_mapping, market_state_contract=market_state_consistency_contract, provider_sdk_version=provider_sdk_version, opend_server_version=opend_server_version, runtime_evidence_window_seconds=runtime_evidence_window_seconds, reason_codes=(_blocker(error),), batches=failure_context.get("batches", ()))  # type: ignore[arg-type]

        batches = self._batch_records(runtime, discovery, screens, snapshots, market_states, plates)
        failure_context["batches"] = batches
        screen_rows = tuple(row for page in screens for row in _records(page.raw_response))
        snapshot_rows = tuple(row for batch in snapshots for row in _records(batch.raw_response))
        raw_market_state_rows = tuple(row for batch in market_states for row in _raw_rows(batch.raw_response))
        market_state_rows = tuple(row for row in raw_market_state_rows if isinstance(row, Mapping))
        screen_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        snapshot_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        market_state_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in screen_rows:
            code = _text(_field(row, "code", "futu_code"))
            if code is not None:
                screen_groups[code].append(row)
        for row in snapshot_rows:
            code = _text(_field(row, "code", "futu_code"))
            if code is not None:
                snapshot_groups[code].append(row)
        market_state_shape_invalid = len(market_state_rows) != len(raw_market_state_rows)
        for row in market_state_rows:
            code = _text(_field(row, "code", "futu_code"))
            market_state = _text(_field(row, "market_state"))
            if code is None or market_state is None:
                market_state_shape_invalid = True
            else:
                market_state_groups[code].append(row)
        expected_codes = set(codes)
        if (
            market_state_shape_invalid
            or set(screen_groups) != expected_codes
            or set(snapshot_groups) != expected_codes
            or set(market_state_groups) != expected_codes
            or any(len(rows) != 1 for rows in screen_groups.values())
            or any(len(rows) != 1 for rows in snapshot_groups.values())
            or any(len(rows) != 1 for rows in market_state_groups.values())
        ):
            return self._failed_attempt(as_of_session=as_of_session, observed_at_utc=observed_at_utc, mapping=active_status_mapping, market_state_contract=market_state_consistency_contract, provider_sdk_version=provider_sdk_version, opend_server_version=opend_server_version, runtime_evidence_window_seconds=runtime_evidence_window_seconds, reason_codes=("UNIVERSE_FRESHNESS_BLOCKER",), batches=batches)
        screen_by_code = {code: rows[0] for code, rows in screen_groups.items()}
        snapshot_by_code = {code: rows[0] for code, rows in snapshot_groups.items()}
        plates_by_code: dict[str, list[RawPlateEvidence]] = defaultdict(list)
        all_snapshot_rows = tuple(snapshot_by_code.values())
        preflight = self._preflight(
            as_of_session=as_of_session,
            observed_at_utc=observed_at_utc,
            provider_sdk_version=provider_sdk_version,
            opend_server_version=opend_server_version,
            snapshots=all_snapshot_rows,
            market_states=tuple(rows[0] for rows in market_state_groups.values()),
            market_state_consistency_contract=market_state_consistency_contract,
        )
        failure_context["preflight"] = preflight

        provenance_cache: dict[str, EvidenceProvenance] = {}
        def provenance(code: str, refs: Sequence[EvidenceReference]) -> EvidenceProvenance:
            key = code + "|" + "|".join(ref.source_record_sha256 for ref in refs)
            if key not in provenance_cache:
                provenance_cache[key] = EvidenceProvenance("FUTU", provider_sdk_version, "futu-opend/raw-v1", "futu-universe-gateway/v1", observed_at_utc, tuple(refs))
            return provenance_cache[key]

        for batch in plates:
            for row in _records(batch.raw_response):
                code = _text(_field(row, "code", "futu_code"))
                plate_code, plate_name, plate_type = _text(_field(row, "plate_code", "code")), _text(_field(row, "plate_name", "name")), _text(_field(row, "plate_type", "type"))
                if code and plate_code and plate_name and plate_type:
                    ref = self._reference("futu-owner-plates", f"futu://owner-plates/{code}", batch.response_hash)
                    plates_by_code[code].append(RawPlateEvidence(plate_code, plate_name, plate_type, provenance(code, (ref,))))

        evidence: list[UniverseSecurityEvidence] = []
        failure_context["evidence"] = evidence
        global_reasons: list[str] = []
        for row in discovery_rows:
            code, stock_id = _text(_field(row, "code", "futu_code")), _text(_field(row, "stock_id", "id"))
            if code is None or stock_id is None:
                global_reasons.extend(("FUTU_SCHEMA_BLOCKER", "UNIVERSE_INCOMPLETE_BLOCKER"))
                continue
            screen, snapshot = screen_by_code.get(code), snapshot_by_code.get(code)
            if screen is None or snapshot is None:
                global_reasons.append("UNIVERSE_INCOMPLETE_BLOCKER")
            refs = [self._reference("futu-discovery", f"futu://discovery/{code}", next(batch.response_hash for batch in discovery if row in _records(batch.raw_response)))]
            if screen is not None:
                page = next(page for page in screens if screen in _records(page.raw_response))
                refs.append(self._reference("futu-screening", f"futu://screening/{code}", page.response_hash))
            if snapshot is not None:
                batch = next(batch for batch in snapshots if snapshot in _records(batch.raw_response))
                refs.append(self._reference("futu-market-snapshot", f"futu://snapshot/{code}", batch.response_hash))
            item_provenance = provenance(code, refs)
            classification_reason_codes: tuple[str, ...] = ()
            try:
                classification = classification_provider.classification_evidence(stock_id, code, observed_at_utc)
            except Exception:
                classification = ()
                global_reasons.append("CLASSIFICATION_EVIDENCE_BLOCKER")
            if any(type(item) is not SecurityClassificationEvidence for item in classification):
                global_reasons.append("CLASSIFICATION_EVIDENCE_BLOCKER")
                classification = ()
            elif not classification:
                classification_reason_codes = ("CLASSIFICATION_EVIDENCE_BLOCKER",)
            liquidity_reasons: tuple[str, ...] = ()
            listing_reasons: tuple[str, ...] = ()
            evidence.append(UniverseSecurityEvidence(
                "universe-security-evidence/v1", stock_id, code,
                _text(_field(screen, "symbol", "code")) or code.removeprefix("US."),
                _text(_field(screen, "name")) or _text(_field(row, "name")) or code,
                _text(_field(row, "exchange_type", "exchange")), _text(_field(row, "stock_type", "security_type")),
                _field(row, "delisting"), _field(snapshot, "suspension"), _text(_field(snapshot, "sec_status", "security_status", "status")),
                _decimal(_field(screen, "price", "last_price"), "price_usd"), _decimal(_field(screen, "market_cap", "total_market_val"), "market_cap_usd"), item_provenance,
                RawIndustryEvidence(_text(_field(screen, "industry")), item_provenance), tuple(plates_by_code[code]), tuple(classification),
                LiquidityEvidence("FUTU_AVG_TURNOVER_20D", "futu-screening-liquidity/v1", _decimal(_field(screen, "avg_turnover", "avg_turnover_20d"), "avg_turnover_20d_usd"), None, 20, "USD", _text(_field(screen, "avg_turnover", "avg_turnover_20d")), item_provenance, liquidity_reasons),
                ListingHistoryEvidence("FUTU_LISTED_DAYS", "futu-screening-listing-history/v1", _integer(_field(screen, "listed_days")), None, _text(_field(screen, "listed_days")), item_provenance, listing_reasons),
                classification_reason_codes,
            ))
        if global_reasons:
            return self._failed_attempt(as_of_session=as_of_session, observed_at_utc=observed_at_utc, mapping=active_status_mapping, market_state_contract=market_state_consistency_contract, provider_sdk_version=provider_sdk_version, opend_server_version=opend_server_version, runtime_evidence_window_seconds=runtime_evidence_window_seconds, reason_codes=global_reasons, batches=batches, evidence=evidence, preflight=preflight)

        by_stock: dict[str, set[str]] = defaultdict(set)
        by_code: dict[str, set[str]] = defaultdict(set)
        for item in evidence:
            by_stock[item.stock_id].add(item.futu_code)
            by_code[item.futu_code].add(item.stock_id)
        ledger: list[IdentityLedgerEntry] = []
        failure_context["ledger"] = ledger
        if any(len(stock_ids) > 1 for stock_ids in by_code.values()):
            for item in evidence:
                ledger.append(IdentityLedgerEntry(item.stock_id, item.futu_code, Decision.UNKNOWN, "UNIVERSE_IDENTITY_BLOCKER", tuple(by_code[item.futu_code]), tuple(by_stock[item.stock_id]), item.provenance.references))
            return self._failed_attempt(as_of_session=as_of_session, observed_at_utc=observed_at_utc, mapping=active_status_mapping, market_state_contract=market_state_consistency_contract, provider_sdk_version=provider_sdk_version, opend_server_version=opend_server_version, runtime_evidence_window_seconds=runtime_evidence_window_seconds, reason_codes=("UNIVERSE_IDENTITY_BLOCKER",), batches=batches, evidence=evidence, ledger=ledger, preflight=preflight)

        prerequisites: list[SecurityEvaluationPrerequisites] = []
        for item in evidence:
            codes = by_stock[item.stock_id]
            identity_decision = Decision.UNKNOWN if len(codes) > 1 else Decision.PASS
            identity_reason = "UNIVERSE_IDENTITY_BLOCKER" if len(codes) > 1 else "IDENTITY_RECONCILED"
            ledger.append(IdentityLedgerEntry(item.stock_id, item.futu_code, identity_decision, identity_reason, tuple(by_code[item.futu_code]), tuple(codes), item.provenance.references, reconciliation_completed=identity_decision is Decision.PASS))
            prerequisites.append(SecurityEvaluationPrerequisites(item.stock_id, item.futu_code, self.normalized_active_status(delisting=item.delisting, suspension=item.suspension, raw_status=item.security_status_raw, evidence_references=item.provenance.references, mapping=active_status_mapping, provider="FUTU", provider_sdk_version=provider_sdk_version, opend_server_version=opend_server_version), NormalizedPrerequisiteDecision(identity_decision, identity_reason, item.provenance.references)))
        prerequisite_hash = prerequisites_sha256(prerequisites)
        failure_context["prerequisites"] = prerequisites
        return self._failed_attempt(
            as_of_session=as_of_session,
            observed_at_utc=observed_at_utc,
            mapping=active_status_mapping,
            market_state_contract=market_state_consistency_contract,
            provider_sdk_version=provider_sdk_version,
            opend_server_version=opend_server_version,
            runtime_evidence_window_seconds=runtime_evidence_window_seconds,
            reason_codes=preflight.reason_codes or ("UNIVERSE_FRESHNESS_BLOCKER",),
            batches=batches,
            evidence=evidence,
            prerequisites=prerequisites,
            ledger=ledger,
            preflight=preflight,
        )
