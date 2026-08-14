from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, DefaultContext, Inexact, Rounded, localcontext
import re

import pytest

from tv_quant.pattern_finder.universe_foundation.evidence import (
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
    decimal_from_source,
    evidence_record_sha256,
    quantize_usd_cent,
)


UTC_NOW = datetime(2026, 8, 15, 1, 2, 3, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _reference(*, locator: str = "futu://screening/US.AAPL") -> EvidenceReference:
    return EvidenceReference(
        source_id="futu-screening-v2",
        source_locator=locator,
        source_record_sha256=SHA_A,
    )


def _provenance(
    *,
    provider_version: str = "futu-api/9.4",
    schema_version: str = "futu-screening-schema/v2",
    locator: str = "futu://screening/US.AAPL",
) -> EvidenceProvenance:
    return EvidenceProvenance(
        provider="FUTU",
        provider_version=provider_version,
        source_version="opend/9.4",
        schema_version=schema_version,
        observed_at_utc=UTC_NOW,
        references=[_reference(locator=locator)],
    )


def _security_evidence(
    *,
    provider_version: str = "futu-api/9.4",
    schema_version: str = "universe-security-evidence/v1",
    locator: str = "futu://screening/US.AAPL",
    industry: str = "Technology",
    plate_name: str = "Cloud Computing",
) -> UniverseSecurityEvidence:
    provenance = _provenance(
        provider_version=provider_version,
        locator=locator,
    )
    return UniverseSecurityEvidence(
        schema_version=schema_version,
        stock_id="1001",
        futu_code="US.AAPL",
        symbol="AAPL",
        name="Apple Inc.",
        exchange_raw="NASDAQ",
        security_type_raw="STOCK",
        delisting=False,
        suspension=False,
        security_status_raw="NORMAL",
        price_usd=Decimal("225.10"),
        market_cap_usd=Decimal("3400000000000.00"),
        provenance=provenance,
        raw_industry=RawIndustryEvidence(raw_value=industry, provenance=provenance),
        raw_plates=[
            RawPlateEvidence(
                plate_code="P2",
                plate_name="Mega Cap",
                plate_type="OTHER",
                provenance=provenance,
            ),
            RawPlateEvidence(
                plate_code="P1",
                plate_name=plate_name,
                plate_type="CONCEPT",
                provenance=provenance,
            ),
        ],
        classification_evidence=[
            SecurityClassificationEvidence(
                normalized_class="COMMON_STOCK",
                provider="APPROVED_SECURITY_MASTER",
                provider_value="Common Stock",
                observed_at_utc=UTC_NOW,
                source_version="security-master/2026-08-15",
                source_record_sha256=SHA_B,
                confidence="AUTHORITATIVE",
                notes="Explicit issue subtype.",
                reference=_reference(locator="security-master://1001"),
                verified_by=None,
            )
        ],
        liquidity=LiquidityEvidence(
            metric_id="FUTU_AVG_TURNOVER_20D",
            evidence_version="futu-screening-liquidity/v1",
            avg_turnover_20d_usd=Decimal("90000000.00"),
            avg_volume_20d_shares=Decimal("400000.00"),
            window_days=20,
            currency="USD",
            raw_value="90000000.00",
            provenance=provenance,
            reason_codes=[],
        ),
        listing_history=ListingHistoryEvidence(
            metric_id="FUTU_LISTED_DAYS",
            evidence_version="futu-screening-listing-history/v1",
            listed_days=10000,
            listing_date=date(1980, 12, 12),
            raw_value="10000",
            provenance=provenance,
            reason_codes=[],
        ),
        reason_codes=[],
    )


def test_contract_enums_freeze_shared_status_vocabulary() -> None:
    assert tuple(item.value for item in Decision) == (
        "PASS",
        "FAIL",
        "UNKNOWN",
        "NOT_APPLICABLE",
    )
    assert tuple(item.value for item in AttemptStatus) == ("SUCCEEDED", "FAILED")
    assert tuple(item.value for item in Completeness) == ("COMPLETE", "INCOMPLETE")


def test_decimal_from_source_requires_a_finite_deterministic_string() -> None:
    assert decimal_from_source("001.2300", field_id="price") == Decimal("1.2300")
    assert decimal_from_source("-1.25", field_id="delta", allow_negative=True) == Decimal(
        "-1.25"
    )

    for invalid in (1.25, Decimal("1.25"), True, None, "NaN", "Infinity", "-Infinity", ""):
        with pytest.raises(ValueError, match="price"):
            decimal_from_source(invalid, field_id="price")  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="non-negative"):
        decimal_from_source("-0.01", field_id="price")

    for invalid_flag in (1, "yes", None):
        with pytest.raises(ValueError, match="allow_negative"):
            decimal_from_source(
                "-0.01",
                field_id="price",
                allow_negative=invalid_flag,  # type: ignore[arg-type]
            )


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("0.004", Decimal("0.00")),
        ("0.005", Decimal("0.00")),
        ("0.006", Decimal("0.01")),
        ("0.015", Decimal("0.02")),
    ),
)
def test_quantize_usd_cent_uses_context_invariant_half_even(
    source: str, expected: Decimal
) -> None:
    with localcontext() as context:
        context.prec = 2
        assert quantize_usd_cent(source, field_id="turnover") == expected


def test_quantize_usd_cent_ignores_caller_traps_and_exponent_bounds() -> None:
    with localcontext() as context:
        context.prec = 2
        context.Emin = 0
        context.Emax = 0
        context.traps[Inexact] = True
        context.traps[Rounded] = True

        assert quantize_usd_cent("0.006", field_id="turnover") == Decimal("0.01")


def test_quantize_usd_cent_ignores_mutated_default_context_traps() -> None:
    original_traps = dict(DefaultContext.traps)
    try:
        DefaultContext.traps[Inexact] = True
        DefaultContext.traps[Rounded] = True

        assert quantize_usd_cent("0.006", field_id="turnover") == Decimal("0.01")
    finally:
        for signal, enabled in original_traps.items():
            DefaultContext.traps[signal] = enabled


def test_evidence_is_deeply_immutable_and_normalizes_nested_collections() -> None:
    evidence = _security_evidence()

    assert isinstance(evidence.raw_plates, tuple)
    assert isinstance(evidence.classification_evidence, tuple)
    assert isinstance(evidence.provenance.references, tuple)
    assert isinstance(evidence.reason_codes, tuple)
    assert tuple(plate.plate_code for plate in evidence.raw_plates) == ("P1", "P2")

    with pytest.raises(FrozenInstanceError):
        evidence.symbol = "MSFT"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        evidence.raw_industry.raw_value = "Hardware"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        evidence.raw_plates.append(evidence.raw_plates[0])  # type: ignore[attr-defined]


def test_evidence_requires_utc_and_lowercase_sha256() -> None:
    with pytest.raises(ValueError, match="UTC"):
        replace(_provenance(), observed_at_utc=datetime(2026, 8, 15, 1, 2, 3))
    with pytest.raises(ValueError, match="UTC"):
        replace(
            _provenance(),
            observed_at_utc=UTC_NOW.astimezone(timezone(timedelta(hours=8))),
        )

    for invalid_hash in ("A" * 64, "a" * 63, "g" * 64):
        with pytest.raises(ValueError, match="lowercase SHA-256"):
            replace(_reference(), source_record_sha256=invalid_hash)


def test_raw_industry_all_plates_and_versions_are_preserved() -> None:
    evidence = _security_evidence()

    assert evidence.schema_version == "universe-security-evidence/v1"
    assert evidence.provenance.provider == "FUTU"
    assert evidence.provenance.provider_version == "futu-api/9.4"
    assert evidence.provenance.source_version == "opend/9.4"
    assert evidence.provenance.schema_version == "futu-screening-schema/v2"
    assert evidence.raw_industry.raw_value == "Technology"
    assert tuple(
        (plate.plate_code, plate.plate_name, plate.plate_type)
        for plate in evidence.raw_plates
    ) == (
        ("P1", "Cloud Computing", "CONCEPT"),
        ("P2", "Mega Cap", "OTHER"),
    )


def test_collection_input_order_does_not_change_canonical_record_hash() -> None:
    evidence = _security_evidence()
    reversed_evidence = replace(
        evidence,
        raw_plates=list(reversed(evidence.raw_plates)),
        classification_evidence=list(reversed(evidence.classification_evidence)),
        reason_codes=["Z_REASON", "A_REASON"],
    )
    sorted_evidence = replace(
        evidence,
        reason_codes=["A_REASON", "Z_REASON"],
    )

    assert evidence_record_sha256(reversed_evidence) == evidence_record_sha256(
        sorted_evidence
    )


def test_tied_plate_sort_fields_still_have_order_independent_hashes() -> None:
    evidence = _security_evidence()
    original_plate = evidence.raw_plates[0]
    other_plate = replace(
        original_plate,
        provenance=_provenance(locator="futu://plates/US.AAPL?page=2"),
    )

    left = replace(evidence, raw_plates=[original_plate, other_plate])
    right = replace(evidence, raw_plates=[other_plate, original_plate])

    assert evidence_record_sha256(left) == evidence_record_sha256(right)


def test_tied_classification_sort_fields_still_have_order_independent_hashes() -> None:
    evidence = _security_evidence()
    original = evidence.classification_evidence[0]
    other = replace(
        original,
        notes="Second independent record.",
        reference=_reference(locator="security-master://1001/record-2"),
    )

    left = replace(evidence, classification_evidence=[original, other])
    right = replace(evidence, classification_evidence=[other, original])

    assert evidence_record_sha256(left) == evidence_record_sha256(right)


@pytest.mark.parametrize(
    "changed",
    (
        _security_evidence(provider_version="futu-api/9.5"),
        _security_evidence(schema_version="universe-security-evidence/v2"),
        _security_evidence(locator="futu://screening/US.AAPL?page=2"),
        _security_evidence(industry="Consumer Electronics"),
        _security_evidence(plate_name="Mobile Devices"),
    ),
)
def test_record_hash_is_sensitive_to_provenance_versions_references_and_raw_evidence(
    changed: UniverseSecurityEvidence,
) -> None:
    original_hash = evidence_record_sha256(_security_evidence())
    changed_hash = evidence_record_sha256(changed)

    assert re.fullmatch(r"[0-9a-f]{64}", changed_hash)
    assert changed_hash != original_hash
