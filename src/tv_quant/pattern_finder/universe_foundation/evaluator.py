"""Pure, fail-closed evaluation of one normalized universe-security record."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from .classification import ClassificationResult
from .evidence import (
    Decision,
    EvidenceProvenance,
    EvidenceReference,
    LiquidityEvidence,
    ListingHistoryEvidence,
    UniverseSecurityEvidence,
    quantize_usd_cent,
)
from .profiles import Exchange, UniverseProfile


_STAGE_IDS = (
    "S1_IDENTITY_VALID",
    "S2_EXCHANGE_ALLOWED",
    "S3_SECURITY_CLASS_ALLOWED",
    "S4_ACTIVE_STATUS_ALLOWED",
    "S5_PRICE_ALLOWED",
    "S6_MARKET_CAP_ALLOWED",
    "S7_SECTOR_INDUSTRY_ALLOWED",
    "S8_LISTING_HISTORY_ALLOWED",
    "S9_LIQUIDITY_ALLOWED",
)
_MEMBERSHIP_DECISIONS = frozenset({Decision.PASS, Decision.FAIL, Decision.UNKNOWN})
_USD_CENT = Decimal("0.01")
_KNOWN_EXCHANGES = frozenset((*tuple(item.value for item in Exchange), "OTC"))


def _non_empty(value: object, field_id: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_id}: non-empty string required")
    return value


def _reference_key(reference: EvidenceReference) -> tuple[str, str, str]:
    return (
        reference.source_id,
        reference.source_locator,
        reference.source_record_sha256,
    )


def _references(values: Iterable[EvidenceReference], field_id: str) -> tuple[EvidenceReference, ...]:
    references = tuple(values)
    if any(type(item) is not EvidenceReference for item in references):
        raise ValueError(f"{field_id}: EvidenceReference values required")
    return tuple(sorted(references, key=_reference_key))


@dataclass(frozen=True, slots=True)
class NormalizedPrerequisiteDecision:
    decision: Decision
    reason_code: str
    evidence_references: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        if type(self.decision) is not Decision or self.decision not in _MEMBERSHIP_DECISIONS:
            raise ValueError("decision: PASS, FAIL, or UNKNOWN required")
        _non_empty(self.reason_code, "reason_code")
        references = _references(self.evidence_references, "evidence_references")
        if self.decision in (Decision.PASS, Decision.FAIL) and not references:
            raise ValueError("evidence_references: PASS/FAIL requires reference")
        object.__setattr__(self, "evidence_references", references)


@dataclass(frozen=True, slots=True)
class SecurityEvaluationPrerequisites:
    stock_id: str
    futu_code: str
    active_status: NormalizedPrerequisiteDecision | None
    identity: NormalizedPrerequisiteDecision | None

    def __post_init__(self) -> None:
        _non_empty(self.stock_id, "stock_id")
        _non_empty(self.futu_code, "futu_code")
        for field_id in ("active_status", "identity"):
            value = getattr(self, field_id)
            if value is not None and type(value) is not NormalizedPrerequisiteDecision:
                raise ValueError(f"{field_id}: NormalizedPrerequisiteDecision or None required")


@dataclass(frozen=True, slots=True)
class FieldDecision:
    field_id: str
    raw_value: object
    normalized_value: object
    operator: str | None
    threshold: object
    decision: Decision
    reason_code: str
    evidence_source: str | None
    evidence_observed_at_utc: object | None
    evidence_version: str | None
    evidence_references: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        _non_empty(self.field_id, "field_id")
        if self.operator is not None:
            _non_empty(self.operator, "operator")
        if type(self.decision) is not Decision or self.decision not in _MEMBERSHIP_DECISIONS:
            raise ValueError("decision: PASS, FAIL, or UNKNOWN required")
        _non_empty(self.reason_code, "reason_code")
        if self.evidence_source is not None:
            _non_empty(self.evidence_source, "evidence_source")
        if self.evidence_version is not None:
            _non_empty(self.evidence_version, "evidence_version")
        object.__setattr__(
            self,
            "evidence_references",
            _references(self.evidence_references, "evidence_references"),
        )


@dataclass(frozen=True, slots=True)
class SecurityEvaluation:
    stock_id: str
    futu_code: str
    symbol: str
    name: str
    field_decisions: tuple[FieldDecision, ...]
    first_exit_stage: str | None
    first_exit_reason_code: str | None
    is_member: bool
    is_quarantined: bool

    def __post_init__(self) -> None:
        for field_id in ("stock_id", "futu_code", "symbol", "name"):
            _non_empty(getattr(self, field_id), field_id)
        decisions = tuple(self.field_decisions)
        if tuple(item.field_id for item in decisions) != _STAGE_IDS:
            raise ValueError("field_decisions: fixed S1-S9 order required")
        if any(type(item) is not FieldDecision for item in decisions):
            raise ValueError("field_decisions: FieldDecision values required")
        object.__setattr__(self, "field_decisions", decisions)
        first = next((item for item in decisions if item.decision is not Decision.PASS), None)
        expected_stage = None if first is None else first.field_id
        expected_reason = None if first is None else first.reason_code
        if self.first_exit_stage != expected_stage or self.first_exit_reason_code != expected_reason:
            raise ValueError("first exit must match the first non-PASS decision")
        if type(self.is_member) is not bool or type(self.is_quarantined) is not bool:
            raise ValueError("membership and quarantine flags must be bool")
        expected_member = all(item.decision is Decision.PASS for item in decisions)
        expected_quarantined = any(item.decision is Decision.UNKNOWN for item in decisions)
        if self.is_member is not expected_member or self.is_quarantined is not expected_quarantined:
            raise ValueError("membership and quarantine flags must derive from field decisions")


def _provenance_fields(
    provenance: EvidenceProvenance,
) -> tuple[str, object, str, tuple[EvidenceReference, ...]]:
    return (
        provenance.provider,
        provenance.observed_at_utc,
        provenance.source_version,
        provenance.references,
    )


def _field(
    field_id: str,
    raw_value: object,
    normalized_value: object,
    operator: str | None,
    threshold: object,
    decision: Decision,
    reason_code: str,
    provenance: EvidenceProvenance | None = None,
    references: tuple[EvidenceReference, ...] = (),
    evidence_version: str | None = None,
    evidence_source: str | None = None,
    evidence_observed_at_utc: object | None = None,
) -> FieldDecision:
    source = evidence_source
    observed = evidence_observed_at_utc
    version = evidence_version
    if provenance is not None:
        provenance_source, provenance_observed, provenance_version, provenance_references = _provenance_fields(provenance)
        if source is None:
            source = provenance_source
        if observed is None:
            observed = provenance_observed
        if version is None:
            version = provenance_version
        if not references:
            references = provenance_references
    return FieldDecision(
        field_id,
        raw_value,
        normalized_value,
        operator,
        threshold,
        decision,
        reason_code,
        source,
        observed,
        version,
        references,
    )


def _project_prerequisite(
    field_id: str,
    prerequisite: NormalizedPrerequisiteDecision | None,
    unknown_reason: str,
) -> FieldDecision:
    if prerequisite is None or prerequisite.decision is Decision.UNKNOWN:
        return _field(
            field_id,
            None if prerequisite is None else prerequisite.decision.value,
            None if prerequisite is None else prerequisite.decision.value,
            None,
            None,
            Decision.UNKNOWN,
            unknown_reason,
            references=() if prerequisite is None else prerequisite.evidence_references,
        )
    return _field(
        field_id,
        prerequisite.decision.value,
        prerequisite.decision.value,
        None,
        None,
        prerequisite.decision,
        prerequisite.reason_code,
        references=prerequisite.evidence_references,
    )


def _threshold(
    field_id: str,
    value: Decimal | None,
    minimum: Decimal | None,
    maximum: Decimal | None,
    provenance: EvidenceProvenance,
    missing_reason: str,
) -> FieldDecision:
    if minimum is None and maximum is None:
        operator: str | None = None
        threshold: object = None
    elif minimum is None:
        operator = "<="
        threshold = maximum
    elif maximum is None:
        operator = ">="
        threshold = minimum
    else:
        operator = ">= AND <="
        threshold = (minimum, maximum)
    if value is None:
        return _field(field_id, None, None, operator, threshold, Decision.UNKNOWN, missing_reason, provenance)
    if minimum is not None and value < minimum:
        return _field(field_id, value, value, ">=", minimum, Decision.FAIL, "BELOW_MINIMUM", provenance)
    if maximum is not None and value > maximum:
        return _field(field_id, value, value, "<=", maximum, Decision.FAIL, "ABOVE_MAXIMUM", provenance)
    return _field(field_id, value, value, operator, threshold, Decision.PASS, "WITHIN_BOUNDS", provenance)


def compare_liquidity_cross_check(
    authoritative_source: str, cross_check_source: str
) -> FieldDecision:
    """Compare two source strings after frozen cent normalization."""

    try:
        authoritative = quantize_usd_cent(authoritative_source, field_id="authoritative_source")
        cross_check = quantize_usd_cent(cross_check_source, field_id="cross_check_source")
    except ValueError:
        return _field(
            "LIQUIDITY_CROSS_CHECK",
            (authoritative_source, cross_check_source),
            None,
            "abs_diff <=",
            _USD_CENT,
            Decision.UNKNOWN,
            "LIQUIDITY_CROSS_CHECK_INVALID",
        )
    difference = abs(authoritative - cross_check)
    decision = Decision.PASS if difference <= _USD_CENT else Decision.UNKNOWN
    reason = "LIQUIDITY_CROSS_CHECK_MATCH" if decision is Decision.PASS else "LIQUIDITY_EVIDENCE_CONFLICT"
    return _field(
        "LIQUIDITY_CROSS_CHECK",
        (authoritative_source, cross_check_source),
        (authoritative, cross_check),
        "abs_diff <=",
        _USD_CENT,
        decision,
        reason,
    )


def _exchange_decision(profile: UniverseProfile, evidence: UniverseSecurityEvidence) -> FieldDecision:
    raw = evidence.exchange_raw
    if raw is None:
        return _field("S2_EXCHANGE_ALLOWED", raw, None, "in", None, Decision.UNKNOWN, "EXCHANGE_UNKNOWN", evidence.provenance)
    normalized = raw.strip().upper()
    allowed = tuple(sorted(item.value for item in profile.filters.exchanges))
    if normalized in allowed:
        return _field("S2_EXCHANGE_ALLOWED", raw, normalized, "in", allowed, Decision.PASS, "EXCHANGE_ALLOWED", evidence.provenance)
    if normalized in _KNOWN_EXCHANGES:
        return _field("S2_EXCHANGE_ALLOWED", raw, normalized, "in", allowed, Decision.FAIL, "EXCHANGE_NOT_ALLOWED", evidence.provenance)
    return _field("S2_EXCHANGE_ALLOWED", raw, normalized or None, "in", allowed, Decision.UNKNOWN, "EXCHANGE_UNKNOWN", evidence.provenance)


def _classification_decision(profile: UniverseProfile, classification: ClassificationResult, provenance: EvidenceProvenance) -> FieldDecision:
    allowed = tuple(sorted(item.value for item in profile.filters.allowed_security_classes))
    if classification.decision is Decision.PASS and classification.normalized_class in allowed:
        decision = Decision.PASS
    elif classification.decision is Decision.FAIL or classification.normalized_class not in allowed:
        decision = Decision.FAIL if classification.decision is not Decision.UNKNOWN else Decision.UNKNOWN
    else:
        decision = Decision.UNKNOWN
    classification_references = tuple(
        item.reference for item in classification.evidence if item.reference is not None
    )
    source = observed_at = source_version = None
    if classification.evidence:
        first_evidence = classification.evidence[0]
        source = first_evidence.provider
        observed_at = first_evidence.observed_at_utc
        source_version = first_evidence.source_version
    return _field(
        "S3_SECURITY_CLASS_ALLOWED",
        classification.normalized_class,
        classification.normalized_class,
        "in",
        allowed,
        decision,
        classification.reason_code,
        provenance,
        classification_references,
        source_version,
        source,
        observed_at,
    )


def _listing_decision(profile: UniverseProfile, listing: ListingHistoryEvidence) -> FieldDecision:
    filters = profile.filters
    if listing.metric_id != filters.listing_history_metric_id or listing.evidence_version != filters.listing_history_evidence_version:
        return _field("S8_LISTING_HISTORY_ALLOWED", listing.raw_value, listing.listed_days, ">=", filters.min_listed_days, Decision.UNKNOWN, "LISTING_HISTORY_EVIDENCE_MISMATCH", listing.provenance, evidence_version=listing.evidence_version)
    if "LISTING_HISTORY_CONFLICT" in listing.reason_codes:
        return _field("S8_LISTING_HISTORY_ALLOWED", listing.raw_value, listing.listed_days, ">=", filters.min_listed_days, Decision.UNKNOWN, "LISTING_HISTORY_CONFLICT", listing.provenance, evidence_version=listing.evidence_version)
    if listing.listed_days is None:
        return _field("S8_LISTING_HISTORY_ALLOWED", listing.raw_value, None, ">=", filters.min_listed_days, Decision.UNKNOWN, "LISTING_HISTORY_MISSING", listing.provenance, evidence_version=listing.evidence_version)
    if filters.min_listed_days is not None and listing.listed_days < filters.min_listed_days:
        return _field("S8_LISTING_HISTORY_ALLOWED", listing.raw_value, listing.listed_days, ">=", filters.min_listed_days, Decision.FAIL, "BELOW_MINIMUM", listing.provenance, evidence_version=listing.evidence_version)
    return _field("S8_LISTING_HISTORY_ALLOWED", listing.raw_value, listing.listed_days, ">=", filters.min_listed_days, Decision.PASS, "LISTING_HISTORY_ALLOWED", listing.provenance, evidence_version=listing.evidence_version)


def _liquidity_decision(profile: UniverseProfile, liquidity: LiquidityEvidence) -> FieldDecision:
    filters = profile.filters
    if liquidity.metric_id != filters.liquidity_metric_id or liquidity.evidence_version != filters.liquidity_evidence_version or liquidity.currency != "USD" or liquidity.window_days != 20:
        return _field("S9_LIQUIDITY_ALLOWED", liquidity.raw_value, liquidity.avg_turnover_20d_usd, ">=", filters.min_avg_dollar_volume_20d_usd, Decision.UNKNOWN, "LIQUIDITY_EVIDENCE_MISMATCH", liquidity.provenance, evidence_version=liquidity.evidence_version)
    if "LIQUIDITY_EVIDENCE_CONFLICT" in liquidity.reason_codes:
        return _field("S9_LIQUIDITY_ALLOWED", liquidity.raw_value, liquidity.avg_turnover_20d_usd, ">=", filters.min_avg_dollar_volume_20d_usd, Decision.UNKNOWN, "LIQUIDITY_EVIDENCE_CONFLICT", liquidity.provenance, evidence_version=liquidity.evidence_version)
    return _threshold(
        "S9_LIQUIDITY_ALLOWED",
        liquidity.avg_turnover_20d_usd,
        filters.min_avg_dollar_volume_20d_usd,
        None,
        liquidity.provenance,
        "LIQUIDITY_MISSING",
    )


def evaluate_security(
    profile: UniverseProfile,
    evidence: UniverseSecurityEvidence,
    classification: ClassificationResult,
    prerequisites: SecurityEvaluationPrerequisites | None,
) -> SecurityEvaluation:
    """Evaluate all fixed S1-S9 stages without provider or cross-security interpretation."""

    if type(profile) is not UniverseProfile or type(evidence) is not UniverseSecurityEvidence:
        raise ValueError("UniverseProfile and UniverseSecurityEvidence required")
    if type(classification) is not ClassificationResult:
        raise ValueError("ClassificationResult required")
    matches = (
        type(prerequisites) is SecurityEvaluationPrerequisites
        and prerequisites.stock_id == evidence.stock_id
        and prerequisites.futu_code == evidence.futu_code
    )
    identity = prerequisites.identity if matches else None
    active = prerequisites.active_status if matches else None
    filters = profile.filters
    sector_all = filters.sectors == "ALL" and filters.industries == "ALL"
    decisions = (
        _project_prerequisite("S1_IDENTITY_VALID", identity, "UNIVERSE_IDENTITY_BLOCKER"),
        _exchange_decision(profile, evidence),
        _classification_decision(profile, classification, evidence.provenance),
        _project_prerequisite("S4_ACTIVE_STATUS_ALLOWED", active, "ACTIVE_STATUS_UNKNOWN"),
        _threshold("S5_PRICE_ALLOWED", evidence.price_usd, filters.min_price_usd, filters.max_price_usd, evidence.provenance, "PRICE_MISSING"),
        _threshold("S6_MARKET_CAP_ALLOWED", evidence.market_cap_usd, filters.min_market_cap_usd, filters.max_market_cap_usd, evidence.provenance, "MARKET_CAP_MISSING"),
        _field("S7_SECTOR_INDUSTRY_ALLOWED", evidence.raw_industry.raw_value, evidence.raw_industry.raw_value, None, "ALL", Decision.PASS if sector_all else Decision.UNKNOWN, "SECTOR_INDUSTRY_ALL" if sector_all else "SECTOR_INDUSTRY_UNSUPPORTED", evidence.raw_industry.provenance),
        _listing_decision(profile, evidence.listing_history),
        _liquidity_decision(profile, evidence.liquidity),
    )
    first = next((item for item in decisions if item.decision is not Decision.PASS), None)
    is_member = all(item.decision is Decision.PASS for item in decisions)
    return SecurityEvaluation(
        evidence.stock_id,
        evidence.futu_code,
        evidence.symbol,
        evidence.name,
        decisions,
        None if first is None else first.field_id,
        None if first is None else first.reason_code,
        is_member,
        any(item.decision is Decision.UNKNOWN for item in decisions),
    )
