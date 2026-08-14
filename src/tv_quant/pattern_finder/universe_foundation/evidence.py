"""Immutable source evidence and deterministic numeric normalization."""

from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timezone
from decimal import Context, Decimal, InvalidOperation, MAX_EMAX, MIN_EMIN, ROUND_HALF_EVEN
from enum import Enum
import re
from typing import Iterable

from tv_quant.run_manifest import canonical_hash


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL_SOURCE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?\Z")
_USD_CENT = Decimal("0.01")


class Decision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AttemptStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Completeness(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


def _non_empty_string(value: object, field_id: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_id}: non-empty string required")
    return value


def _optional_string(value: object, field_id: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str:
        raise ValueError(f"{field_id}: string or None required")
    return value


def _utc_datetime(value: object, field_id: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timezone.utc.utcoffset(value)
    ):
        raise ValueError(f"{field_id}: UTC datetime required")
    return value


def _sha256(value: object, field_id: str) -> str:
    if type(value) is not str or not _SHA256.fullmatch(value):
        raise ValueError(f"{field_id}: lowercase SHA-256 required")
    return value


def _optional_decimal(value: object, field_id: str) -> Decimal | None:
    if value is None:
        return None
    if type(value) is not Decimal or not value.is_finite():
        raise ValueError(f"{field_id}: finite Decimal or None required")
    if value < 0:
        raise ValueError(f"{field_id}: non-negative Decimal required")
    return value


def _sorted_strings(values: Iterable[str], field_id: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{field_id}: collection of strings required")
    materialized = tuple(values)
    if any(type(value) is not str or not value.strip() for value in materialized):
        raise ValueError(f"{field_id}: non-empty strings required")
    return tuple(sorted(set(materialized)))


def decimal_from_source(
    value: str, *, field_id: str, allow_negative: bool = False
) -> Decimal:
    """Build a finite Decimal from an unambiguous source string."""

    _non_empty_string(field_id, "field_id")
    if type(allow_negative) is not bool:
        raise ValueError("allow_negative: bool required")
    if type(value) is not str or not _DECIMAL_SOURCE.fullmatch(value):
        raise ValueError(f"{field_id}: deterministic decimal source string required")
    try:
        result = Decimal(value)
    except InvalidOperation as error:  # pragma: no cover - regex protects this path
        raise ValueError(f"{field_id}: invalid decimal source string") from error
    if not result.is_finite():
        raise ValueError(f"{field_id}: finite decimal required")
    if result < 0 and not allow_negative:
        raise ValueError(f"{field_id}: non-negative decimal required")
    return result


def quantize_usd_cent(value: str, *, field_id: str) -> Decimal:
    """Normalize a non-negative USD source string to cents using HALF_EVEN."""

    source = decimal_from_source(value, field_id=field_id)
    digits = len(source.as_tuple().digits)
    integer_digits = max(source.adjusted() + 1, 1) if source else 1
    context = Context(
        prec=max(28, digits + 2, integer_digits + 4),
        rounding=ROUND_HALF_EVEN,
        Emin=MIN_EMIN,
        Emax=MAX_EMAX,
        capitals=1,
        clamp=0,
    )
    return source.quantize(_USD_CENT, context=context)


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    source_id: str
    source_locator: str
    source_record_sha256: str

    def __post_init__(self) -> None:
        _non_empty_string(self.source_id, "source_id")
        _non_empty_string(self.source_locator, "source_locator")
        _sha256(self.source_record_sha256, "source_record_sha256")


def _reference_sort_key(reference: EvidenceReference) -> tuple[str, str, str]:
    return (
        reference.source_id,
        reference.source_locator,
        reference.source_record_sha256,
    )


@dataclass(frozen=True, slots=True)
class EvidenceProvenance:
    provider: str
    provider_version: str
    source_version: str
    schema_version: str
    observed_at_utc: datetime
    references: tuple[EvidenceReference, ...]

    def __post_init__(self) -> None:
        _non_empty_string(self.provider, "provider")
        _non_empty_string(self.provider_version, "provider_version")
        _non_empty_string(self.source_version, "source_version")
        _non_empty_string(self.schema_version, "schema_version")
        _utc_datetime(self.observed_at_utc, "observed_at_utc")
        references = tuple(self.references)
        if any(type(reference) is not EvidenceReference for reference in references):
            raise ValueError("references: EvidenceReference values required")
        object.__setattr__(
            self,
            "references",
            tuple(
                sorted(
                    references,
                    key=_reference_sort_key,
                )
            ),
        )


def _provenance_sort_key(provenance: EvidenceProvenance) -> tuple[object, ...]:
    return (
        provenance.provider,
        provenance.provider_version,
        provenance.source_version,
        provenance.schema_version,
        provenance.observed_at_utc.isoformat(),
        tuple(_reference_sort_key(reference) for reference in provenance.references),
    )


@dataclass(frozen=True, slots=True)
class RawIndustryEvidence:
    raw_value: str | None
    provenance: EvidenceProvenance

    def __post_init__(self) -> None:
        _optional_string(self.raw_value, "raw_industry.raw_value")
        if type(self.provenance) is not EvidenceProvenance:
            raise ValueError("raw_industry.provenance: EvidenceProvenance required")


@dataclass(frozen=True, slots=True)
class RawPlateEvidence:
    plate_code: str
    plate_name: str
    plate_type: str
    provenance: EvidenceProvenance

    def __post_init__(self) -> None:
        _non_empty_string(self.plate_code, "plate_code")
        _non_empty_string(self.plate_name, "plate_name")
        _non_empty_string(self.plate_type, "plate_type")
        if type(self.provenance) is not EvidenceProvenance:
            raise ValueError("plate.provenance: EvidenceProvenance required")


def _plate_sort_key(plate: RawPlateEvidence) -> tuple[object, ...]:
    return (
        plate.plate_code,
        plate.plate_name,
        plate.plate_type,
        _provenance_sort_key(plate.provenance),
    )


@dataclass(frozen=True, slots=True)
class SecurityClassificationEvidence:
    normalized_class: str
    provider: str
    provider_value: str
    observed_at_utc: datetime
    source_version: str
    source_record_sha256: str
    confidence: str
    notes: str
    reference: EvidenceReference | None
    verified_by: str | None

    def __post_init__(self) -> None:
        _non_empty_string(self.normalized_class, "normalized_class")
        _non_empty_string(self.provider, "classification.provider")
        _non_empty_string(self.provider_value, "provider_value")
        _utc_datetime(self.observed_at_utc, "classification.observed_at_utc")
        _non_empty_string(self.source_version, "classification.source_version")
        _sha256(self.source_record_sha256, "classification.source_record_sha256")
        _non_empty_string(self.confidence, "confidence")
        if type(self.notes) is not str:
            raise ValueError("notes: string required")
        if self.reference is not None and type(self.reference) is not EvidenceReference:
            raise ValueError("reference: EvidenceReference or None required")
        if self.verified_by is not None:
            _non_empty_string(self.verified_by, "verified_by")


def _classification_sort_key(
    evidence: SecurityClassificationEvidence,
) -> tuple[object, ...]:
    reference_key = (
        (False, ("", "", ""))
        if evidence.reference is None
        else (True, _reference_sort_key(evidence.reference))
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
        evidence.verified_by is not None,
        evidence.verified_by or "",
    )


@dataclass(frozen=True, slots=True)
class LiquidityEvidence:
    metric_id: str
    evidence_version: str
    avg_turnover_20d_usd: Decimal | None
    avg_volume_20d_shares: Decimal | None
    window_days: int
    currency: str
    raw_value: str | None
    provenance: EvidenceProvenance
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty_string(self.metric_id, "liquidity.metric_id")
        _non_empty_string(self.evidence_version, "liquidity.evidence_version")
        _optional_decimal(self.avg_turnover_20d_usd, "avg_turnover_20d_usd")
        _optional_decimal(self.avg_volume_20d_shares, "avg_volume_20d_shares")
        if type(self.window_days) is not int or self.window_days <= 0:
            raise ValueError("window_days: positive integer required")
        _non_empty_string(self.currency, "currency")
        _optional_string(self.raw_value, "liquidity.raw_value")
        if type(self.provenance) is not EvidenceProvenance:
            raise ValueError("liquidity.provenance: EvidenceProvenance required")
        object.__setattr__(
            self, "reason_codes", _sorted_strings(self.reason_codes, "liquidity.reason_codes")
        )


@dataclass(frozen=True, slots=True)
class ListingHistoryEvidence:
    metric_id: str
    evidence_version: str
    listed_days: int | None
    listing_date: date | None
    raw_value: str | None
    provenance: EvidenceProvenance
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty_string(self.metric_id, "listing_history.metric_id")
        _non_empty_string(self.evidence_version, "listing_history.evidence_version")
        if self.listed_days is not None and (
            type(self.listed_days) is not int or self.listed_days < 0
        ):
            raise ValueError("listed_days: non-negative integer or None required")
        if self.listing_date is not None and type(self.listing_date) is not date:
            raise ValueError("listing_date: date or None required")
        _optional_string(self.raw_value, "listing_history.raw_value")
        if type(self.provenance) is not EvidenceProvenance:
            raise ValueError("listing_history.provenance: EvidenceProvenance required")
        object.__setattr__(
            self,
            "reason_codes",
            _sorted_strings(self.reason_codes, "listing_history.reason_codes"),
        )


@dataclass(frozen=True, slots=True)
class UniverseSecurityEvidence:
    schema_version: str
    stock_id: str
    futu_code: str
    symbol: str
    name: str
    exchange_raw: str | None
    security_type_raw: str | None
    delisting: bool | None
    suspension: bool | None
    security_status_raw: str | None
    price_usd: Decimal | None
    market_cap_usd: Decimal | None
    provenance: EvidenceProvenance
    raw_industry: RawIndustryEvidence
    raw_plates: tuple[RawPlateEvidence, ...]
    classification_evidence: tuple[SecurityClassificationEvidence, ...]
    liquidity: LiquidityEvidence
    listing_history: ListingHistoryEvidence
    reason_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _non_empty_string(self.schema_version, "evidence.schema_version")
        _non_empty_string(self.stock_id, "stock_id")
        _non_empty_string(self.futu_code, "futu_code")
        _non_empty_string(self.symbol, "symbol")
        _non_empty_string(self.name, "name")
        _optional_string(self.exchange_raw, "exchange_raw")
        _optional_string(self.security_type_raw, "security_type_raw")
        if self.delisting is not None and type(self.delisting) is not bool:
            raise ValueError("delisting: bool or None required")
        if self.suspension is not None and type(self.suspension) is not bool:
            raise ValueError("suspension: bool or None required")
        _optional_string(self.security_status_raw, "security_status_raw")
        _optional_decimal(self.price_usd, "price_usd")
        _optional_decimal(self.market_cap_usd, "market_cap_usd")
        if type(self.provenance) is not EvidenceProvenance:
            raise ValueError("provenance: EvidenceProvenance required")
        if type(self.raw_industry) is not RawIndustryEvidence:
            raise ValueError("raw_industry: RawIndustryEvidence required")
        if type(self.liquidity) is not LiquidityEvidence:
            raise ValueError("liquidity: LiquidityEvidence required")
        if type(self.listing_history) is not ListingHistoryEvidence:
            raise ValueError("listing_history: ListingHistoryEvidence required")

        plates = tuple(self.raw_plates)
        if any(type(plate) is not RawPlateEvidence for plate in plates):
            raise ValueError("raw_plates: RawPlateEvidence values required")
        object.__setattr__(
            self,
            "raw_plates",
            tuple(
                sorted(
                    plates,
                    key=_plate_sort_key,
                )
            ),
        )

        classifications = tuple(self.classification_evidence)
        if any(
            type(item) is not SecurityClassificationEvidence for item in classifications
        ):
            raise ValueError(
                "classification_evidence: SecurityClassificationEvidence values required"
            )
        object.__setattr__(
            self,
            "classification_evidence",
            tuple(
                sorted(
                    classifications,
                    key=_classification_sort_key,
                )
            ),
        )
        object.__setattr__(
            self, "reason_codes", _sorted_strings(self.reason_codes, "reason_codes")
        )


def _canonical_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _canonical_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return _utc_datetime(value, "datetime").isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical Decimal must be finite")
        return format(value, "f")
    if isinstance(value, tuple):
        return [_canonical_value(item) for item in value]
    if value is None or type(value) in (bool, int, str):
        return value
    raise ValueError(f"unsupported canonical evidence value: {type(value).__name__}")


def evidence_record_sha256(evidence: UniverseSecurityEvidence) -> str:
    """Hash the complete normalized evidence record with the repository hash owner."""

    if type(evidence) is not UniverseSecurityEvidence:
        raise ValueError("UniverseSecurityEvidence required")
    payload = _canonical_value(evidence)
    if not isinstance(payload, dict):  # pragma: no cover - dataclass always maps
        raise ValueError("canonical evidence mapping required")
    return canonical_hash(payload)
