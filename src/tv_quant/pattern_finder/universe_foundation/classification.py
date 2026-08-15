"""Fail-closed security classification from explicit subtype evidence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .evidence import Decision, SecurityClassificationEvidence


CLASSIFICATION_UNKNOWN = "CLASSIFICATION_UNKNOWN"
CLASSIFICATION_EVIDENCE_CONFLICT = "CLASSIFICATION_EVIDENCE_CONFLICT"

_COMMON_STOCK = "COMMON_STOCK"
_UNKNOWN = "UNKNOWN"
_RELIABLE_CONFIDENCE = frozenset({"AUTHORITATIVE", "CORROBORATED"})
_SUBTYPE_PROVIDERS = frozenset({"APPROVED_SECURITY_MASTER", "MANUAL_VERIFIED"})
_ALLOWED_PROVIDERS = _SUBTYPE_PROVIDERS | {"FUTU_STATIC"}
_FUTU_STATIC_CLASSES = frozenset({"ETF", "WARRANT"})
_NORMALIZED_CLASSES = frozenset(
    {_COMMON_STOCK, "ADR", "ETF", "PREFERRED", "WARRANT", "UNIT", "OTHER", _UNKNOWN}
)
_RESOLVABLE_CLASSES = _NORMALIZED_CLASSES - {_UNKNOWN}
_EXPLICIT_FUTU_NON_STOCK = {
    "ETF": "ETF",
    "WARRANT": "WARRANT",
    "BWRT": "WARRANT",
}


def _evidence_sort_key(evidence: SecurityClassificationEvidence) -> tuple[object, ...]:
    reference = evidence.reference
    reference_key = (
        ("", "", "")
        if reference is None
        else (
            reference.source_id,
            reference.source_locator,
            reference.source_record_sha256,
        )
    )
    return (
        evidence.normalized_class,
        evidence.provider,
        evidence.provider_value,
        evidence.observed_at_utc.isoformat(),
        evidence.source_version,
        evidence.source_record_sha256,
        evidence.confidence,
        evidence.notes,
        reference_key,
        evidence.verified_by or "",
    )


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    decision: Decision
    normalized_class: str
    reason_code: str
    evidence: tuple[SecurityClassificationEvidence, ...]

    def __post_init__(self) -> None:
        if type(self.decision) is not Decision:
            raise ValueError("decision: Decision required")
        if self.normalized_class not in _NORMALIZED_CLASSES:
            raise ValueError("normalized_class: unsupported classification")
        if type(self.reason_code) is not str or not self.reason_code.strip():
            raise ValueError("reason_code: non-empty string required")
        evidence = tuple(self.evidence)
        if any(type(item) is not SecurityClassificationEvidence for item in evidence):
            raise ValueError("evidence: SecurityClassificationEvidence values required")
        object.__setattr__(self, "evidence", tuple(sorted(evidence, key=_evidence_sort_key)))


def _has_admissible_provenance(evidence: SecurityClassificationEvidence) -> bool:
    if evidence.normalized_class not in _RESOLVABLE_CLASSES:
        return False
    if evidence.provider not in _ALLOWED_PROVIDERS:
        return False
    if evidence.reference is None:
        return False
    if evidence.reference.source_record_sha256 != evidence.source_record_sha256:
        return False
    if evidence.provider == "FUTU_STATIC":
        return evidence.normalized_class in _FUTU_STATIC_CLASSES
    if evidence.provider == "MANUAL_VERIFIED":
        return evidence.verified_by is not None
    return True


def _is_reliable(evidence: SecurityClassificationEvidence) -> bool:
    return (
        _has_admissible_provenance(evidence)
        and evidence.confidence in _RELIABLE_CONFIDENCE
    )


def _result(
    decision: Decision,
    normalized_class: str,
    reason_code: str,
    evidence: tuple[SecurityClassificationEvidence, ...],
) -> ClassificationResult:
    return ClassificationResult(
        decision=decision,
        normalized_class=normalized_class,
        reason_code=reason_code,
        evidence=evidence,
    )


def resolve_classification(
    top_level_futu_type: str | None,
    evidence: Sequence[SecurityClassificationEvidence],
) -> ClassificationResult:
    """Resolve only explicit typed classification evidence."""

    materialized = tuple(evidence)
    if any(type(item) is not SecurityClassificationEvidence for item in materialized):
        raise ValueError("evidence: SecurityClassificationEvidence values required")
    ordered = tuple(sorted(materialized, key=_evidence_sort_key))
    admissible_classes = {
        item.normalized_class for item in ordered if _has_admissible_provenance(item)
    }
    reliable_classes = {item.normalized_class for item in ordered if _is_reliable(item)}

    top_level = (
        top_level_futu_type.strip().upper()
        if type(top_level_futu_type) is str and top_level_futu_type.strip()
        else None
    )
    top_level_class = _EXPLICIT_FUTU_NON_STOCK.get(top_level or "")
    explicit_classes = set(admissible_classes)
    if top_level_class is not None:
        explicit_classes.add(top_level_class)
    if len(explicit_classes) > 1:
        return _result(
            Decision.UNKNOWN,
            _UNKNOWN,
            CLASSIFICATION_EVIDENCE_CONFLICT,
            ordered,
        )
    if top_level != "STOCK" and top_level_class is None:
        return _result(Decision.UNKNOWN, _UNKNOWN, CLASSIFICATION_UNKNOWN, ordered)

    resolved_classes = set(reliable_classes)
    if top_level_class is not None:
        resolved_classes.add(top_level_class)

    if len(resolved_classes) > 1:
        return _result(
            Decision.UNKNOWN,
            _UNKNOWN,
            CLASSIFICATION_EVIDENCE_CONFLICT,
            ordered,
        )
    if not resolved_classes:
        return _result(Decision.UNKNOWN, _UNKNOWN, CLASSIFICATION_UNKNOWN, ordered)

    normalized_class = next(iter(resolved_classes))
    if normalized_class == _COMMON_STOCK:
        return _result(
            Decision.PASS,
            normalized_class,
            "CLASSIFICATION_COMMON_STOCK",
            ordered,
        )
    return _result(
        Decision.FAIL,
        normalized_class,
        f"CLASSIFICATION_EXCLUDED_{normalized_class}",
        ordered,
    )
