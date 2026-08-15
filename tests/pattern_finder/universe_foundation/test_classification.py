from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import inspect

import pytest

from tv_quant.pattern_finder.universe_foundation import (
    AppendOnlyClassificationLedger,
    ClassificationResult,
    Decision,
    EvidenceReference,
    SecurityClassificationEvidence,
    SecurityMasterProvider,
    resolve_classification,
)


UTC_NOW = datetime(2026, 8, 15, 12, 0, tzinfo=timezone.utc)
SHA_A = "a" * 64
SHA_B = "b" * 64


def _reference(
    *,
    locator: str = "security-master://records/1001",
    record_hash: str = SHA_A,
) -> EvidenceReference:
    return EvidenceReference(
        source_id="approved-security-master",
        source_locator=locator,
        source_record_sha256=record_hash,
    )


def _evidence(
    normalized_class: str,
    *,
    confidence: str = "AUTHORITATIVE",
    provider: str = "APPROVED_SECURITY_MASTER",
    observed_at_utc: datetime = UTC_NOW,
    record_hash: str = SHA_A,
    reference: EvidenceReference | None = None,
    verified_by: str | None = None,
) -> SecurityClassificationEvidence:
    if reference is None and provider != "MANUAL_VERIFIED":
        reference = _reference(record_hash=record_hash)
    return SecurityClassificationEvidence(
        normalized_class=normalized_class,
        provider=provider,
        provider_value=normalized_class.replace("_", " ").title(),
        observed_at_utc=observed_at_utc,
        source_version="security-master/2026-08-15",
        source_record_sha256=record_hash,
        confidence=confidence,
        notes="Explicit issue subtype.",
        reference=reference,
        verified_by=verified_by,
    )


def test_security_master_provider_freezes_the_evidence_port_signature() -> None:
    signature = inspect.signature(SecurityMasterProvider.classification_evidence)

    assert tuple(signature.parameters) == (
        "self",
        "stock_id",
        "futu_code",
        "as_of_utc",
    )
    assert signature.return_annotation == "tuple[SecurityClassificationEvidence, ...]"


@pytest.mark.parametrize(
    ("top_level_type", "normalized_class"),
    (("ETF", "ETF"), ("WARRANT", "WARRANT"), ("BWRT", "WARRANT")),
)
def test_explicit_futu_non_stock_type_fails_with_specific_classification(
    top_level_type: str,
    normalized_class: str,
) -> None:
    result = resolve_classification(top_level_type, ())

    assert result == ClassificationResult(
        decision=Decision.FAIL,
        normalized_class=normalized_class,
        reason_code=f"CLASSIFICATION_EXCLUDED_{normalized_class}",
        evidence=(),
    )


def test_stock_alone_and_missing_evidence_fail_closed() -> None:
    assert resolve_classification("STOCK", ()) == ClassificationResult(
        decision=Decision.UNKNOWN,
        normalized_class="UNKNOWN",
        reason_code="CLASSIFICATION_UNKNOWN",
        evidence=(),
    )
    assert resolve_classification(None, ()).reason_code == "CLASSIFICATION_UNKNOWN"


@pytest.mark.parametrize("confidence", ("AUTHORITATIVE", "CORROBORATED"))
def test_reliable_explicit_common_stock_is_the_only_pass_path(confidence: str) -> None:
    evidence = _evidence("COMMON_STOCK", confidence=confidence)

    result = resolve_classification("STOCK", (evidence,))

    assert result.decision is Decision.PASS
    assert result.normalized_class == "COMMON_STOCK"
    assert result.reason_code == "CLASSIFICATION_COMMON_STOCK"
    assert result.evidence == (evidence,)


@pytest.mark.parametrize(
    "normalized_class",
    ("ADR", "ETF", "PREFERRED", "WARRANT", "UNIT", "OTHER"),
)
def test_reliable_explicit_non_common_evidence_fails(normalized_class: str) -> None:
    result = resolve_classification("STOCK", (_evidence(normalized_class),))

    assert result.decision is Decision.FAIL
    assert result.normalized_class == normalized_class
    assert result.reason_code == f"CLASSIFICATION_EXCLUDED_{normalized_class}"


def test_common_and_non_common_evidence_conflict_deterministically() -> None:
    common = _evidence("COMMON_STOCK", record_hash=SHA_A)
    preferred = _evidence(
        "PREFERRED",
        record_hash=SHA_B,
        reference=_reference(locator="security-master://records/1001-preferred", record_hash=SHA_B),
    )

    left = resolve_classification("STOCK", (common, preferred))
    right = resolve_classification("STOCK", (preferred, common))

    assert left == right
    assert left.decision is Decision.UNKNOWN
    assert left.normalized_class == "UNKNOWN"
    assert left.reason_code == "CLASSIFICATION_EVIDENCE_CONFLICT"
    assert left.evidence == (common, preferred)


def test_explicit_top_level_type_conflicting_with_common_evidence_is_unknown() -> None:
    result = resolve_classification("ETF", (_evidence("COMMON_STOCK"),))

    assert result.decision is Decision.UNKNOWN
    assert result.reason_code == "CLASSIFICATION_EVIDENCE_CONFLICT"


def test_ambiguous_or_incomplete_manual_evidence_cannot_pass() -> None:
    ambiguous = _evidence("COMMON_STOCK", confidence="AMBIGUOUS")
    missing_locator_and_verifier = _evidence(
        "COMMON_STOCK",
        provider="MANUAL_VERIFIED",
        reference=None,
        verified_by=None,
    )

    assert resolve_classification("STOCK", (ambiguous,)).decision is Decision.UNKNOWN
    assert (
        resolve_classification("STOCK", (missing_locator_and_verifier,)).decision
        is Decision.UNKNOWN
    )


@pytest.mark.parametrize(
    "evidence",
    (
        _evidence("COMMON_STOCK", provider="TICKER_HEURISTIC"),
        _evidence("COMMON_STOCK", provider="FUTU_STATIC"),
        replace(
            _evidence("COMMON_STOCK", provider="APPROVED_SECURITY_MASTER"),
            reference=None,
        ),
    ),
)
def test_unapproved_or_incomplete_common_evidence_cannot_pass(
    evidence: SecurityClassificationEvidence,
) -> None:
    result = resolve_classification("STOCK", (evidence,))

    assert result.decision is Decision.UNKNOWN
    assert result.reason_code == "CLASSIFICATION_UNKNOWN"


def test_ambiguous_non_common_evidence_still_conflicts_with_common() -> None:
    common = _evidence("COMMON_STOCK", confidence="AUTHORITATIVE")
    preferred = _evidence(
        "PREFERRED",
        confidence="AMBIGUOUS",
        record_hash=SHA_B,
        reference=_reference(locator="security-master://records/1001-preferred", record_hash=SHA_B),
    )

    result = resolve_classification("STOCK", (common, preferred))

    assert result.decision is Decision.UNKNOWN
    assert result.normalized_class == "UNKNOWN"
    assert result.reason_code == "CLASSIFICATION_EVIDENCE_CONFLICT"


def test_complete_manual_evidence_uses_observation_time_as_verification_time() -> None:
    manual = _evidence(
        "COMMON_STOCK",
        provider="MANUAL_VERIFIED",
        reference=_reference(locator="sec-filing://accession/1001"),
        verified_by="reviewer@example.com",
    )

    result = resolve_classification("STOCK", (manual,))

    assert result.decision is Decision.PASS
    assert result.evidence[0].observed_at_utc is UTC_NOW
    assert result.evidence[0].verified_by == "reviewer@example.com"


@pytest.mark.parametrize("top_level_type", ("UNKNOWN", "STOCKISH", "US.AAPL", "AAPL-W"))
def test_unknown_top_level_values_and_ticker_shaped_strings_never_infer_common(
    top_level_type: str,
) -> None:
    result = resolve_classification(top_level_type, ())

    assert result.decision is Decision.UNKNOWN
    assert result.normalized_class == "UNKNOWN"
    assert result.reason_code == "CLASSIFICATION_UNKNOWN"


@pytest.mark.parametrize("top_level_type", (None, "UNKNOWN", "STOCKISH"))
def test_unknown_futu_top_level_cannot_be_promoted_by_common_subtype_evidence(
    top_level_type: str | None,
) -> None:
    result = resolve_classification(top_level_type, (_evidence("COMMON_STOCK"),))

    assert result.decision is Decision.UNKNOWN
    assert result.normalized_class == "UNKNOWN"
    assert result.reason_code == "CLASSIFICATION_UNKNOWN"


def test_resolver_api_has_no_symbol_name_suffix_or_regex_inputs() -> None:
    signature = inspect.signature(resolve_classification)

    assert tuple(signature.parameters) == ("top_level_futu_type", "evidence")


def test_classification_result_is_deeply_immutable() -> None:
    result = resolve_classification("STOCK", (_evidence("COMMON_STOCK"),))

    assert isinstance(result.evidence, tuple)
    with pytest.raises(FrozenInstanceError):
        result.reason_code = "CHANGED"  # type: ignore[misc]


def test_ledger_preserves_explicit_identity_evidence_and_historical_as_of(tmp_path) -> None:
    ledger = AppendOnlyClassificationLedger(tmp_path)
    original = _evidence("COMMON_STOCK", observed_at_utc=UTC_NOW)
    correction_time = UTC_NOW + timedelta(days=1)
    correction = _evidence(
        "PREFERRED",
        observed_at_utc=correction_time,
        record_hash=SHA_B,
        reference=_reference(locator="security-master://records/1001-v2", record_hash=SHA_B),
    )
    other_security = _evidence("ETF", record_hash=SHA_B)

    ledger.append("1001", original)
    ledger.append("2002", other_security)
    ledger.append("1001", correction)

    reloaded = AppendOnlyClassificationLedger(tmp_path)
    assert reloaded.get("1001", as_of_utc=UTC_NOW) == (original,)
    assert reloaded.get("1001", as_of_utc=correction_time) == (original, correction)
    assert reloaded.get("2002", as_of_utc=UTC_NOW) == (other_security,)
    assert len((tmp_path / "classification.jsonl").read_text(encoding="utf-8").splitlines()) == 3


def test_ledger_rejects_non_utc_as_of_and_blank_identity(tmp_path) -> None:
    ledger = AppendOnlyClassificationLedger(tmp_path)
    evidence = _evidence("COMMON_STOCK")

    with pytest.raises(ValueError, match="stock_id"):
        ledger.append(" ", evidence)
    with pytest.raises(ValueError, match="UTC"):
        ledger.get("1001", as_of_utc=UTC_NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    "malformed_line",
    (
        "not-json\n",
        '{"stock_id":"1001"}\n',
        '{"stock_id":"1001","stock_id":"2002","evidence":{}}\n',
    ),
)
def test_malformed_or_incomplete_ledger_fails_closed(tmp_path, malformed_line: str) -> None:
    (tmp_path / "classification.jsonl").write_text(malformed_line, encoding="utf-8")
    ledger = AppendOnlyClassificationLedger(tmp_path)

    with pytest.raises(ValueError, match="classification ledger"):
        ledger.get("1001", as_of_utc=UTC_NOW)


def test_ledger_round_trip_preserves_complete_manual_provenance(tmp_path) -> None:
    manual = _evidence(
        "COMMON_STOCK",
        provider="MANUAL_VERIFIED",
        reference=_reference(locator="sec-filing://accession/1001"),
        verified_by="reviewer@example.com",
    )
    ledger = AppendOnlyClassificationLedger(tmp_path)

    ledger.append("1001", manual)
    restored = ledger.get("1001", as_of_utc=UTC_NOW)[0]

    assert restored == manual
    assert restored.reference == manual.reference
    assert restored.source_version == "security-master/2026-08-15"
    assert restored.source_record_sha256 == SHA_A
    assert restored.verified_by == "reviewer@example.com"


def test_correction_does_not_mutate_the_original_evidence(tmp_path) -> None:
    ledger = AppendOnlyClassificationLedger(tmp_path)
    original = _evidence("COMMON_STOCK")
    correction = replace(
        original,
        normalized_class="ADR",
        provider_value="ADR",
        observed_at_utc=UTC_NOW + timedelta(days=1),
        source_record_sha256=SHA_B,
        reference=_reference(locator="security-master://records/1001-v2", record_hash=SHA_B),
    )

    ledger.append("1001", original)
    ledger.append("1001", correction)

    assert ledger.get("1001", as_of_utc=UTC_NOW) == (original,)
