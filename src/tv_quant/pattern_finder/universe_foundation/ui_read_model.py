"""Read-only projection for the initialized universe profile page."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

import streamlit as st

from .classification import ClassificationResult
from .evaluator import SecurityEvaluationPrerequisites, evaluate_security
from .evidence import UniverseSecurityEvidence
from .profiles import RecordState, UniverseProfile
from .registry import ProfileRegistry


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
