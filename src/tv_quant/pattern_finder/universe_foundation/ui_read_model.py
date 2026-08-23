"""Read-only projection for the initialized universe profile page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
from typing import Any
from uuid import UUID

import streamlit as st

from .classification import ClassificationResult
from .evaluator import SecurityEvaluationPrerequisites, evaluate_security
from .evidence import EvidenceReference, UniverseSecurityEvidence
from .profiles import RecordState, UniverseProfile
from .registry import ProfileRegistry
from .snapshots import (
    SnapshotValidationError,
    UniverseSnapshot,
    UniverseSnapshotRow,
    UniverseSnapshotStore,
)


_DECISION_ITEM_LABELS = {
    "S1_IDENTITY_VALID": "Identity verification",
    "S2_EXCHANGE_ALLOWED": "Exchange eligibility",
    "S3_SECURITY_CLASS_ALLOWED": "Security classification",
    "S4_ACTIVE_STATUS_ALLOWED": "Active trading status",
    "S5_PRICE_ALLOWED": "Share price",
    "S6_MARKET_CAP_ALLOWED": "Market capitalization",
    "S7_SECTOR_INDUSTRY_ALLOWED": "Sector and industry",
    "S8_LISTING_HISTORY_ALLOWED": "Listing history",
    "S9_LIQUIDITY_ALLOWED": "20-day average dollar volume",
}

_REASON_EXPLANATIONS = {
    "UNIVERSE_IDENTITY_BLOCKER": (
        "The identity record could not be reconciled, so this security is held in "
        "Quarantine and cannot enter CORE."
    ),
    "ACTIVE_STATUS_UNKNOWN": (
        "The active trading status could not be verified, so this security cannot "
        "enter CORE."
    ),
    "CLASSIFICATION_UNKNOWN": (
        "The security subtype evidence is insufficient, so this security cannot "
        "enter CORE."
    ),
    "LIQUIDITY_EVIDENCE_CONFLICT": (
        "The liquidity evidence conflicts across sources, so this security is held "
        "in Quarantine."
    ),
    "LISTING_HISTORY_CONFLICT": (
        "The listing-history evidence conflicts across sources, so this security is "
        "held in Quarantine."
    ),
}


@dataclass(frozen=True, slots=True)
class ProfileConditionRow:
    """One immutable, display-ready frozen profile condition."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ProfileUiState:
    """Display-only state for a single initialized published profile."""

    profile_version_id: str
    display_name: str
    record_state: str
    published_at_utc: datetime
    change_note: str
    content_sha256: str
    filter_content_sha256: str
    conditions: tuple[ProfileConditionRow, ...]


@dataclass(frozen=True, slots=True)
class DecisionDetailUi:
    """Display-only projection of one immutable Task 6 field decision."""

    field_id: str
    decision: str
    actual_value: str
    normalized_value: str
    operator: str | None
    threshold: str
    reason_code: str
    evidence_source: str | None
    evidence_references: tuple[str, ...]
    evidence_version: str | None
    authoritative_metric: str | None = None
    evidence_observed_at_utc: str | None = None
    stock_id: str | None = None
    futu_code: str | None = None
    symbol: str | None = None
    name: str | None = None
    evaluation_status: str | None = None
    is_member: bool | None = None
    is_quarantined: bool | None = None
    first_exit_stage: str | None = None
    first_exit_reason_code: str | None = None
    profile_version_id: str | None = None
    profile_content_sha256: str | None = None
    draft_id: str | None = None
    draft_content_sha256: str | None = None
    active_status_decision: str | None = None
    active_status_reason_code: str | None = None
    active_status_evidence_references: tuple[str, ...] = ()
    identity_decision: str | None = None
    identity_reason_code: str | None = None
    identity_evidence_references: tuple[str, ...] = ()
    decisions: tuple["DecisionDetailUi", ...] = ()
    classification_evidence: tuple["ClassificationEvidenceUi", ...] = ()
    raw_industry: str | None = None
    raw_industry_source: str | None = None
    raw_industry_provider_version: str | None = None
    raw_industry_source_version: str | None = None
    raw_industry_schema_version: str | None = None
    raw_industry_observed_at_utc: str | None = None
    raw_industry_references: tuple[str, ...] = ()
    raw_plates: tuple["RawPlateUi", ...] = ()
    listing_history_cross_check: tuple[str, ...] = ()
    raw_evidence_references: tuple[str, ...] = ()
    raw_evidence_sha256: str | None = None
    exchange_raw: str | None = None
    exchange_normalized: str | None = None
    security_type_raw: str | None = None
    security_class_normalized: str | None = None
    delisting: bool | None = None
    suspension: bool | None = None
    security_status_raw: str | None = None
    price_usd: str | None = None
    price_observed_at_utc: str | None = None
    market_cap_usd: str | None = None
    market_cap_observed_at_utc: str | None = None
    liquidity_metric_id: str | None = None
    liquidity_evidence_version: str | None = None
    avg_turnover_20d_usd: str | None = None
    liquidity_window_end: str | None = None
    avg_volume_20d_shares: str | None = None
    listing_history_metric_id: str | None = None
    listing_history_evidence_version: str | None = None
    listing_date: str | None = None
    listed_days: int | None = None
    sector_mapping_version: str | None = None
    active_status_mapping_provider: str | None = None
    active_status_mapping_provider_sdk_version: str | None = None
    active_status_mapping_opend_server_version: str | None = None
    active_status_mapping_version: str | None = None
    active_status_mapping_qualification_references: tuple[str, ...] = ()
    active_status_mapping_sha256: str | None = None
    prerequisites_sha256: str | None = None
    members_sha256: str | None = None
    snapshot_content_sha256: str | None = None
    snapshot_record_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class EvaluationUiState:
    """Display-only projection of one immutable Task 6 security evaluation."""

    stock_id: str
    futu_code: str
    symbol: str
    name: str
    profile_version_id: str
    profile_content_sha256: str
    is_member: bool
    is_quarantined: bool
    first_exit_stage: str | None
    first_exit_reason_code: str | None
    decisions: tuple[DecisionDetailUi, ...]


@dataclass(frozen=True, slots=True)
class ClassificationEvidenceUi:
    """One persisted classification evidence record, without interpretation."""

    normalized_class: str
    provider: str
    provider_value: str
    observed_at_utc: str
    source_version: str
    source_record_sha256: str
    confidence: str
    notes: str
    reference: str | None
    verified_by: str | None


@dataclass(frozen=True, slots=True)
class RawPlateUi:
    """One persisted owner-plate row and its provenance."""

    plate_code: str
    plate_name: str
    plate_type: str
    provider: str
    provider_version: str
    source_version: str
    schema_version: str
    observed_at_utc: str
    references: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FunnelStageUi:
    """Display-only projection of one persisted Snapshot funnel stage."""

    stage_order: int
    stage_id: str
    input_count: int
    pass_count: int
    fail_count: int
    unknown_count: int
    quarantine_count: int
    reason_counts: tuple[tuple[str, int], ...]
    output_count: int


@dataclass(frozen=True, slots=True)
class ApiBatchRecordUi:
    """Display-safe copy of one persisted gateway batch binding."""

    endpoint: str
    batch_index: int
    request_hash: str
    response_hash: str
    acquired_at_utc: str
    page_index: int | None


@dataclass(frozen=True, slots=True)
class IdentityLedgerEntryUi:
    """Display-safe copy of one persisted identity-ledger row."""

    stock_id: str
    futu_code: str
    decision: str
    reason_code: str
    competing_stock_ids: tuple[str, ...]
    competing_futu_codes: tuple[str, ...]
    evidence_references: tuple[str, ...]
    reconciliation_completed: bool


@dataclass(frozen=True, slots=True)
class RawApiBatchUi:
    """Display-safe copy of one persisted raw capability probe."""

    endpoint: str
    batch_index: int
    raw_request: object
    raw_response: object
    request_hash: str
    response_hash: str
    ret_code: object
    acquisition_status: str
    acquired_at_utc: str


@dataclass(frozen=True, slots=True)
class SnapshotUiState:
    """Complete read-only projection of one persisted UniverseSnapshot."""

    snapshot_id: str
    snapshot_schema_version: str
    snapshot_kind: str
    completeness: str
    profile_version_id: str | None
    profile_content_sha256: str | None
    draft_id: str | None
    draft_content_sha256: str | None
    as_of_session: str
    created_at_utc: str
    gateway_attempt_id: str
    gateway_attempt_status: str
    gateway_attempt_observed_at_utc: str
    gateway_attempt_reason_codes: tuple[str, ...]
    gateway_preflight_as_of_session: str
    gateway_preflight_observed_at_utc: str
    gateway_preflight_provider_update_time: str | None
    gateway_preflight_market_data_delay_class: str
    gateway_preflight_formal_ready: bool
    gateway_preflight_reason_codes: tuple[str, ...]
    gateway_runtime_evidence_window_seconds: float
    gateway_attempt_sha256: str
    provider_update_time: str | None
    provider: str
    provider_sdk_version: str
    opend_server_version: str
    gateway_batches: tuple[ApiBatchRecordUi, ...]
    gateway_identity_ledger: tuple[IdentityLedgerEntryUi, ...]
    market_data_delay_evidence: tuple[ApiBatchRecordUi, ...]
    realtime_capability_probes: tuple[RawApiBatchUi, ...]
    market_data_delay_class: str
    market_state_consistency_sha256: str
    active_status_mapping_provider: str
    active_status_mapping_provider_sdk_version: str
    active_status_mapping_opend_server_version: str
    active_status_mapping_version: str
    active_status_mapping_qualified_at_utc: str
    active_status_mapping_qualification_references: tuple[str, ...]
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
    snapshot_content_sha256: str
    snapshot_record_sha256: str
    funnel_stages: tuple[FunnelStageUi, ...]
    decisions: tuple[DecisionDetailUi, ...]
    members: tuple[DecisionDetailUi, ...]
    failures: tuple[DecisionDetailUi, ...]
    quarantined: tuple[DecisionDetailUi, ...]


def _text(value: Decimal | int | str | None) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _display_value(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _decision_item_label(field_id: str) -> str:
    return _DECISION_ITEM_LABELS.get(field_id, field_id)


def _reason_explanation(item: DecisionDetailUi) -> str:
    if item.reason_code in _REASON_EXPLANATIONS:
        return _REASON_EXPLANATIONS[item.reason_code]
    if item.decision == "PASS":
        return "This requirement passed based on the cited evidence."
    if item.decision == "FAIL":
        return "This security does not meet this Profile condition."
    return (
        "The required evidence is missing, conflicted, or cannot be verified, so this "
        "security cannot enter CORE."
    )


def _condition_rows(profile: UniverseProfile) -> tuple[ProfileConditionRow, ...]:
    filters = profile.filters
    return (
        ProfileConditionRow("Exchanges", ", ".join(sorted(item.value for item in filters.exchanges))),
        ProfileConditionRow(
            "Allowed security classes",
            ", ".join(sorted(item.value for item in filters.allowed_security_classes)),
        ),
        ProfileConditionRow("Minimum price (USD)", _text(filters.min_price_usd)),
        ProfileConditionRow("Maximum price (USD)", _text(filters.max_price_usd)),
        ProfileConditionRow("Minimum market cap (USD)", _text(filters.min_market_cap_usd)),
        ProfileConditionRow("Maximum market cap (USD)", _text(filters.max_market_cap_usd)),
        ProfileConditionRow("Liquidity metric", filters.liquidity_metric_id),
        ProfileConditionRow("Liquidity evidence version", filters.liquidity_evidence_version),
        ProfileConditionRow(
            "Minimum average dollar volume, 20D (USD)",
            _text(filters.min_avg_dollar_volume_20d_usd),
        ),
        ProfileConditionRow(
            "Minimum average volume, 20D (shares)",
            _text(filters.min_avg_volume_20d_shares),
        ),
        ProfileConditionRow("Listing history metric", filters.listing_history_metric_id),
        ProfileConditionRow(
            "Listing history evidence version", filters.listing_history_evidence_version
        ),
        ProfileConditionRow("Minimum listed days", _text(filters.min_listed_days)),
        ProfileConditionRow("Sectors", _text(filters.sectors)),
        ProfileConditionRow("Industries", _text(filters.industries)),
        ProfileConditionRow("Sector mapping version", _text(filters.sector_mapping_version)),
        ProfileConditionRow("Include ETF", _text(filters.include_etf)),
        ProfileConditionRow("Include ADR", _text(filters.include_adr)),
        ProfileConditionRow("Include OTC", _text(filters.include_otc)),
        ProfileConditionRow("Include preferred", _text(filters.include_preferred)),
        ProfileConditionRow("Include warrant", _text(filters.include_warrant)),
        ProfileConditionRow("Include unit", _text(filters.include_unit)),
        ProfileConditionRow("Active only", _text(filters.active_only)),
    )


def load_profile_ui_state(
    registry: ProfileRegistry, profile_version_id: str
) -> ProfileUiState:
    """Project an already initialized published profile without evaluating membership."""

    try:
        profile = registry.get_published(profile_version_id)
    except KeyError as exc:
        raise RuntimeError(
            f"published profile not initialized: {profile_version_id}"
        ) from exc
    if profile.record_state is not RecordState.PUBLISHED:
        raise RuntimeError(f"no current published profile: {profile_version_id}")
    if profile.published_at_utc is None:
        raise RuntimeError(f"published profile is incomplete: {profile_version_id}")
    if profile.content_sha256 is None or profile.filter_content_sha256 is None:
        raise RuntimeError(f"published profile is incomplete: {profile_version_id}")
    return ProfileUiState(
        profile_version_id=profile.profile_version_id,
        display_name=profile.display_name,
        record_state=profile.record_state.value,
        published_at_utc=profile.published_at_utc,
        change_note=profile.change_note,
        content_sha256=profile.content_sha256,
        filter_content_sha256=profile.filter_content_sha256,
        conditions=_condition_rows(profile),
    )


def build_evaluation_ui_state(
    *,
    profile: UniverseProfile,
    evidence: UniverseSecurityEvidence,
    classification: ClassificationResult,
    prerequisites: SecurityEvaluationPrerequisites | None,
) -> EvaluationUiState:
    """Evaluate once through Task 6, then project only that immutable result."""

    evaluation = evaluate_security(profile, evidence, classification, prerequisites)
    if profile.content_sha256 is None:
        raise RuntimeError("evaluation profile must have a content hash")
    decisions = tuple(
        DecisionDetailUi(
            field_id=decision.field_id,
            decision=decision.decision.value,
            actual_value=_display_value(decision.raw_value),
            normalized_value=_display_value(decision.normalized_value),
            operator=decision.operator,
            threshold=_display_value(decision.threshold),
            reason_code=decision.reason_code,
            evidence_source=decision.evidence_source,
            evidence_references=tuple(
                f"{reference.source_id}: {reference.source_locator}"
                for reference in decision.evidence_references
            ),
            evidence_version=decision.evidence_version,
        )
        for decision in evaluation.field_decisions
    )
    return EvaluationUiState(
        stock_id=evaluation.stock_id,
        futu_code=evaluation.futu_code,
        symbol=evaluation.symbol,
        name=evaluation.name,
        profile_version_id=profile.profile_version_id,
        profile_content_sha256=profile.content_sha256,
        is_member=evaluation.is_member,
        is_quarantined=evaluation.is_quarantined,
        first_exit_stage=evaluation.first_exit_stage,
        first_exit_reason_code=evaluation.first_exit_reason_code,
        decisions=decisions,
    )


def _snapshot_reference(reference: object) -> str:
    return (
        f"{reference.source_id}: {reference.source_locator} "
        f"[{reference.source_record_sha256}]"
    )


def _snapshot_references(references: object) -> tuple[str, ...]:
    return tuple(_snapshot_reference(reference) for reference in references)


def _audit_projection(value: object) -> object:
    """Copy persisted audit values into deterministic JSON-safe display values."""

    if value is None or type(value) in (bool, int, float, str):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, EvidenceReference):
        return {
            "source_id": value.source_id,
            "source_locator": value.source_locator,
            "source_record_sha256": value.source_record_sha256,
        }
    if isinstance(value, Mapping):
        return {
            str(key): _audit_projection(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return [_audit_projection(item) for item in value]
    raise SnapshotValidationError(
        f"unsupported persisted audit projection type: {type(value).__name__}"
    )


def _batch_ui(item: object) -> ApiBatchRecordUi:
    return ApiBatchRecordUi(
        endpoint=item.endpoint,
        batch_index=item.batch_index,
        request_hash=item.request_hash,
        response_hash=item.response_hash,
        acquired_at_utc=item.acquired_at_utc.isoformat(),
        page_index=item.page_index,
    )


def _identity_ledger_ui(item: object) -> IdentityLedgerEntryUi:
    return IdentityLedgerEntryUi(
        stock_id=item.stock_id,
        futu_code=item.futu_code,
        decision=item.decision.value,
        reason_code=item.reason_code,
        competing_stock_ids=item.competing_stock_ids,
        competing_futu_codes=item.competing_futu_codes,
        evidence_references=_snapshot_references(item.evidence_references),
        reconciliation_completed=item.reconciliation_completed,
    )


def _probe_ui(item: object) -> RawApiBatchUi:
    return RawApiBatchUi(
        endpoint=item.endpoint,
        batch_index=item.batch_index,
        raw_request=_audit_projection(item.raw_request),
        raw_response=_audit_projection(item.raw_response),
        request_hash=item.request_hash,
        response_hash=item.response_hash,
        ret_code=_audit_projection(item.ret_code),
        acquisition_status=item.acquisition_status,
        acquired_at_utc=item.acquired_at_utc.isoformat(),
    )


def _authoritative_metric(row: UniverseSnapshotRow, field_id: str) -> str:
    if field_id == "S8_LISTING_HISTORY_ALLOWED":
        return row.listing_history_metric_id
    if field_id == "S9_LIQUIDITY_ALLOWED":
        return row.liquidity_metric_id
    return field_id


def _snapshot_field_decisions(row: UniverseSnapshotRow) -> tuple[DecisionDetailUi, ...]:
    return tuple(
        DecisionDetailUi(
            field_id=item.field_id,
            decision=item.decision.value,
            actual_value=_display_value(item.raw_value),
            normalized_value=_display_value(item.normalized_value),
            operator=item.operator,
            threshold=_display_value(item.threshold),
            reason_code=item.reason_code,
            evidence_source=item.evidence_source,
            evidence_references=_snapshot_references(item.evidence_references),
            evidence_version=item.evidence_version,
            authoritative_metric=_authoritative_metric(row, item.field_id),
            evidence_observed_at_utc=(
                None
                if item.evidence_observed_at_utc is None
                else _display_value(item.evidence_observed_at_utc)
            ),
        )
        for item in row.field_decisions
    )


def _snapshot_security_detail(snapshot: UniverseSnapshot, row: UniverseSnapshotRow) -> DecisionDetailUi:
    header = snapshot.header
    decisions = _snapshot_field_decisions(row)
    persisted_decision = (
        "PASS" if row.is_member else "UNKNOWN" if row.is_quarantined else "FAIL"
    )
    evaluation_status = (
        "MEMBER" if row.is_member else "QUARANTINE" if row.is_quarantined else "FAIL"
    )
    classifications = tuple(
        ClassificationEvidenceUi(
            normalized_class=item.normalized_class,
            provider=item.provider,
            provider_value=item.provider_value,
            observed_at_utc=item.observed_at_utc.isoformat(),
            source_version=item.source_version,
            source_record_sha256=item.source_record_sha256,
            confidence=item.confidence,
            notes=item.notes,
            reference=(
                None if item.reference is None else _snapshot_reference(item.reference)
            ),
            verified_by=item.verified_by,
        )
        for item in row.classification_evidence
    )
    plates = tuple(
        RawPlateUi(
            plate_code=item.plate_code,
            plate_name=item.plate_name,
            plate_type=item.plate_type,
            provider=item.provenance.provider,
            provider_version=item.provenance.provider_version,
            source_version=item.provenance.source_version,
            schema_version=item.provenance.schema_version,
            observed_at_utc=item.provenance.observed_at_utc.isoformat(),
            references=_snapshot_references(item.provenance.references),
        )
        for item in row.raw_plates
    )
    return DecisionDetailUi(
        field_id="SECURITY_SUMMARY",
        decision=persisted_decision,
        actual_value="Not applicable",
        normalized_value=evaluation_status,
        operator=None,
        threshold="Not applicable",
        reason_code=row.first_exit_reason_code or "MEMBER",
        evidence_source=None,
        evidence_references=(),
        evidence_version=None,
        authoritative_metric="PERSISTED_SNAPSHOT_EVALUATION",
        stock_id=row.stock_id,
        futu_code=row.futu_code,
        symbol=row.symbol,
        name=row.name,
        evaluation_status=evaluation_status,
        is_member=row.is_member,
        is_quarantined=row.is_quarantined,
        first_exit_stage=row.first_exit_stage,
        first_exit_reason_code=row.first_exit_reason_code,
        profile_version_id=header.profile_version_id,
        profile_content_sha256=header.profile_content_sha256,
        draft_id=header.draft_id,
        draft_content_sha256=header.draft_content_sha256,
        active_status_decision=(
            None if row.active_status_decision is None else row.active_status_decision.value
        ),
        active_status_reason_code=row.active_status_reason_code,
        active_status_evidence_references=_snapshot_references(
            row.active_status_evidence_references
        ),
        identity_decision=(
            None if row.identity_decision is None else row.identity_decision.value
        ),
        identity_reason_code=row.identity_reason_code,
        identity_evidence_references=_snapshot_references(
            row.identity_evidence_references
        ),
        decisions=decisions,
        classification_evidence=classifications,
        raw_industry=row.raw_industry.raw_value,
        raw_industry_source=row.raw_industry.provenance.provider,
        raw_industry_provider_version=(
            row.raw_industry.provenance.provider_version
        ),
        raw_industry_source_version=row.raw_industry.provenance.source_version,
        raw_industry_schema_version=row.raw_industry.provenance.schema_version,
        raw_industry_observed_at_utc=(
            row.raw_industry.provenance.observed_at_utc.isoformat()
        ),
        raw_industry_references=_snapshot_references(
            row.raw_industry.provenance.references
        ),
        raw_plates=plates,
        listing_history_cross_check=row.listing_history_cross_check,
        raw_evidence_references=_snapshot_references(row.raw_evidence_references),
        raw_evidence_sha256=row.raw_evidence_sha256,
        exchange_raw=row.exchange_raw,
        exchange_normalized=row.exchange_normalized,
        security_type_raw=row.security_type_raw,
        security_class_normalized=row.security_class_normalized,
        delisting=row.delisting,
        suspension=row.suspension,
        security_status_raw=row.security_status_raw,
        price_usd=None if row.price_usd is None else format(row.price_usd, "f"),
        price_observed_at_utc=row.price_observed_at_utc.isoformat(),
        market_cap_usd=(
            None if row.market_cap_usd is None else format(row.market_cap_usd, "f")
        ),
        market_cap_observed_at_utc=row.market_cap_observed_at_utc.isoformat(),
        liquidity_metric_id=row.liquidity_metric_id,
        liquidity_evidence_version=row.liquidity_evidence_version,
        avg_turnover_20d_usd=(
            None
            if row.avg_turnover_20d_usd is None
            else format(row.avg_turnover_20d_usd, "f")
        ),
        liquidity_window_end=row.liquidity_window_end.isoformat(),
        avg_volume_20d_shares=(
            None
            if row.avg_volume_20d_shares is None
            else format(row.avg_volume_20d_shares, "f")
        ),
        listing_history_metric_id=row.listing_history_metric_id,
        listing_history_evidence_version=row.listing_history_evidence_version,
        listing_date=None if row.listing_date is None else row.listing_date.isoformat(),
        listed_days=row.listed_days,
        sector_mapping_version=row.sector_mapping_version,
        active_status_mapping_provider=header.active_status_mapping_provider,
        active_status_mapping_provider_sdk_version=(
            header.active_status_mapping_provider_sdk_version
        ),
        active_status_mapping_opend_server_version=(
            header.active_status_mapping_opend_server_version
        ),
        active_status_mapping_version=header.active_status_mapping_version,
        active_status_mapping_qualification_references=_snapshot_references(
            header.active_status_mapping_qualification_references
        ),
        active_status_mapping_sha256=header.active_status_mapping_sha256,
        prerequisites_sha256=header.prerequisites_sha256,
        members_sha256=header.members_sha256,
        snapshot_content_sha256=header.snapshot_content_sha256,
        snapshot_record_sha256=header.snapshot_record_sha256,
    )


def load_snapshot_ui_state(
    store: UniverseSnapshotStore, snapshot_id: UUID
) -> SnapshotUiState:
    """Load one persisted Snapshot and project it without recomputing decisions."""

    snapshot = store.get(snapshot_id)
    if type(snapshot) is not UniverseSnapshot:
        raise SnapshotValidationError(
            "snapshot store get() must return a persisted UniverseSnapshot"
        )
    header = snapshot.header
    decisions = tuple(_snapshot_security_detail(snapshot, row) for row in snapshot.rows)
    stages = tuple(
        FunnelStageUi(
            stage_order=stage.stage_order,
            stage_id=stage.stage_id,
            input_count=stage.input_count,
            pass_count=stage.pass_count,
            fail_count=stage.fail_count,
            unknown_count=stage.unknown_count,
            quarantine_count=stage.unknown_count,
            reason_counts=stage.reason_counts,
            output_count=stage.output_count,
        )
        for stage in snapshot.funnel.stages
    )
    return SnapshotUiState(
        snapshot_id=str(header.universe_snapshot_id),
        snapshot_schema_version=header.snapshot_schema_version,
        snapshot_kind=header.snapshot_kind.value,
        completeness=header.completeness.value,
        profile_version_id=header.profile_version_id,
        profile_content_sha256=header.profile_content_sha256,
        draft_id=header.draft_id,
        draft_content_sha256=header.draft_content_sha256,
        as_of_session=header.as_of_session.isoformat(),
        created_at_utc=header.created_at_utc.isoformat(),
        gateway_attempt_id=header.gateway_attempt_id,
        gateway_attempt_status=header.gateway_attempt_status.value,
        gateway_attempt_observed_at_utc=(
            header.gateway_attempt_observed_at_utc.isoformat()
        ),
        gateway_attempt_reason_codes=header.gateway_attempt_reason_codes,
        gateway_preflight_as_of_session=(
            header.gateway_preflight_as_of_session.isoformat()
        ),
        gateway_preflight_observed_at_utc=(
            header.gateway_preflight_observed_at_utc.isoformat()
        ),
        gateway_preflight_provider_update_time=(
            None
            if header.gateway_preflight_provider_update_time is None
            else header.gateway_preflight_provider_update_time.isoformat()
        ),
        gateway_preflight_market_data_delay_class=(
            header.gateway_preflight_market_data_delay_class
        ),
        gateway_preflight_formal_ready=header.gateway_preflight_formal_ready,
        gateway_preflight_reason_codes=header.gateway_preflight_reason_codes,
        gateway_runtime_evidence_window_seconds=(
            header.gateway_runtime_evidence_window_seconds
        ),
        gateway_attempt_sha256=header.gateway_attempt_sha256,
        provider_update_time=(
            None
            if header.provider_update_time is None
            else header.provider_update_time.isoformat()
        ),
        provider=header.provider,
        provider_sdk_version=header.provider_sdk_version,
        opend_server_version=header.opend_server_version,
        gateway_batches=tuple(_batch_ui(item) for item in header.gateway_batches),
        gateway_identity_ledger=tuple(
            _identity_ledger_ui(item) for item in header.gateway_identity_ledger
        ),
        market_data_delay_evidence=tuple(
            _batch_ui(item) for item in header.market_data_delay_evidence
        ),
        realtime_capability_probes=tuple(
            _probe_ui(item) for item in header.realtime_capability_probes
        ),
        market_data_delay_class=header.market_data_delay_class,
        market_state_consistency_sha256=header.market_state_consistency_sha256,
        active_status_mapping_provider=header.active_status_mapping_provider,
        active_status_mapping_provider_sdk_version=(
            header.active_status_mapping_provider_sdk_version
        ),
        active_status_mapping_opend_server_version=(
            header.active_status_mapping_opend_server_version
        ),
        active_status_mapping_version=header.active_status_mapping_version,
        active_status_mapping_qualified_at_utc=(
            header.active_status_mapping_qualified_at_utc.isoformat()
        ),
        active_status_mapping_qualification_references=_snapshot_references(
            header.active_status_mapping_qualification_references
        ),
        active_status_mapping_sha256=header.active_status_mapping_sha256,
        prerequisites_sha256=header.prerequisites_sha256,
        sector_mapping_version=header.sector_mapping_version,
        liquidity_metric_id=header.liquidity_metric_id,
        liquidity_evidence_version=header.liquidity_evidence_version,
        listing_history_metric_id=header.listing_history_metric_id,
        listing_history_evidence_version=header.listing_history_evidence_version,
        classification_source_versions=header.classification_source_versions,
        candidate_count=header.candidate_count,
        member_count=header.member_count,
        quarantine_count=header.quarantine_count,
        funnel_sha256=header.funnel_sha256,
        members_sha256=header.members_sha256,
        snapshot_content_sha256=header.snapshot_content_sha256,
        snapshot_record_sha256=header.snapshot_record_sha256,
        funnel_stages=stages,
        decisions=decisions,
        members=tuple(item for item in decisions if item.is_member),
        failures=tuple(
            item
            for item in decisions
            if item.is_member is False and item.is_quarantined is False
        ),
        quarantined=tuple(item for item in decisions if item.is_quarantined),
    )


def find_security_decision(
    state: SnapshotUiState, query: str
) -> DecisionDetailUi | None:
    """Find one exact persisted stock ID, Futu code, or symbol projection."""

    if type(query) is not str or not query.strip():
        return None
    needle = query.strip().casefold()
    for item in state.decisions:
        if needle in {
            (item.stock_id or "").casefold(),
            (item.futu_code or "").casefold(),
            (item.symbol or "").casefold(),
        }:
            return item
    return None


def snapshot_ui_download_json(state: SnapshotUiState) -> str:
    """Serialize the complete persisted-Snapshot UI projection for download."""

    if type(state) is not SnapshotUiState:
        raise TypeError("state: SnapshotUiState required")
    return json.dumps(
        asdict(state),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def render_profile_status(
    *, registry: ProfileRegistry, profile_version_id: str
) -> None:
    """Render the published profile fields and frozen conditions only."""

    state = load_profile_ui_state(registry, profile_version_id)
    st.header("当前正式版本")
    st.subheader(state.display_name)
    st.markdown(f"**Profile version:** {state.profile_version_id}")
    st.markdown(f"**Record state:** {state.record_state}")
    st.markdown(f"**Published at (UTC):** {state.published_at_utc.isoformat()}")
    st.markdown(f"**Change note:** {state.change_note}")
    st.subheader("冻结条件")
    for row in state.conditions:
        st.markdown(f"- **{row.label}:** {row.value}")
    st.subheader("Content hashes")
    st.markdown(f"**Profile content SHA-256:** {state.content_sha256}")
    st.markdown(f"**Filter content SHA-256:** {state.filter_content_sha256}")


def render_security_evaluation(*, state: EvaluationUiState) -> None:
    """Render a prebuilt Task 6 evaluation without recomputing any decision."""

    st.header("证券判定结果")
    st.subheader(f"{state.symbol} — {state.name}")
    st.markdown(f"**Stock ID / Futu code:** {state.stock_id} / {state.futu_code}")
    st.markdown(f"**Current Universe Profile:** {state.profile_version_id}")
    st.markdown(
        f"**Profile Version / Hash:** {state.profile_version_id} / "
        f"{state.profile_content_sha256}"
    )
    st.markdown(f"**CORE Member: {'YES' if state.is_member else 'NO'}**")
    st.markdown(f"**Quarantine: {'YES' if state.is_quarantined else 'NO'}**")
    if state.first_exit_stage is not None:
        first_exit = next(
            item for item in state.decisions if item.field_id == state.first_exit_stage
        )
        st.markdown(
            f"**Why not CORE:** {_decision_item_label(first_exit.field_id)} "
            f"({first_exit.field_id}) — {first_exit.reason_code}. "
            f"{_reason_explanation(first_exit)}"
        )
    st.subheader("逐项判断")
    st.dataframe(
        [
            {
                "Decision item": f"{_decision_item_label(item.field_id)} ({item.field_id})",
                "Status": item.decision,
                "Actual value": item.actual_value,
                "Normalized value": item.normalized_value,
                "Operator": item.operator or "Not applicable",
                "Threshold": item.threshold,
                "Reason": item.reason_code,
                "Why": _reason_explanation(item),
                "Evidence source": item.evidence_source or "Not available",
                "Evidence reference": "\n".join(item.evidence_references)
                or "Not available",
                "Evidence version": item.evidence_version or "Not available",
            }
            for item in state.decisions
        ],
        hide_index=True,
        width="stretch",
    )
