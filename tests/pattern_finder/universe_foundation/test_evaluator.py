from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from tv_quant.pattern_finder.universe_foundation import (
    ClassificationResult,
    Decision,
    EvidenceProvenance,
    EvidenceReference,
    LiquidityEvidence,
    ListingHistoryEvidence,
    NormalizedPrerequisiteDecision,
    RawIndustryEvidence,
    RecordState,
    SecurityClassificationEvidence,
    SecurityEvaluationPrerequisites,
    UniverseSecurityEvidence,
    compare_liquidity_cross_check,
    core_v1,
    evaluate_security,
)


UTC_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64


def _reference(locator: str = "futu://screening/US.AAPL") -> EvidenceReference:
    return EvidenceReference("FUTU", locator, SHA)


def _provenance() -> EvidenceProvenance:
    return EvidenceProvenance(
        provider="FUTU",
        provider_version="futu-api/9.4",
        source_version="opend/9.4",
        schema_version="futu-screening/v2",
        observed_at_utc=UTC_NOW,
        references=(_reference(),),
    )


def _evidence(**changes: object) -> UniverseSecurityEvidence:
    provenance = _provenance()
    values: dict[str, object] = {
        "schema_version": "universe-security-evidence/v1",
        "stock_id": "1001",
        "futu_code": "US.AAPL",
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "exchange_raw": "NASDAQ",
        "security_type_raw": "STOCK",
        "delisting": None,
        "suspension": None,
        "security_status_raw": None,
        "price_usd": Decimal("5.00"),
        "market_cap_usd": Decimal("1000000000.00"),
        "provenance": provenance,
        "raw_industry": RawIndustryEvidence("Technology", provenance),
        "raw_plates": (),
        "classification_evidence": (),
        "liquidity": LiquidityEvidence(
            metric_id="FUTU_AVG_TURNOVER_20D",
            evidence_version="futu-screening-liquidity/v1",
            avg_turnover_20d_usd=Decimal("20000000.00"),
            avg_volume_20d_shares=None,
            window_days=20,
            currency="USD",
            raw_value="20000000.00",
            provenance=provenance,
            reason_codes=(),
        ),
        "listing_history": ListingHistoryEvidence(
            metric_id="FUTU_LISTED_DAYS",
            evidence_version="futu-screening-listing-history/v1",
            listed_days=250,
            listing_date=date(1980, 12, 12),
            raw_value="250",
            provenance=provenance,
            reason_codes=(),
        ),
        "reason_codes": (),
    }
    values.update(changes)
    return UniverseSecurityEvidence(**values)  # type: ignore[arg-type]


def _classification(decision: Decision = Decision.PASS) -> ClassificationResult:
    normalized = "COMMON_STOCK" if decision is Decision.PASS else "ETF"
    return ClassificationResult(
        decision=decision,
        normalized_class=normalized,
        reason_code=(
            "CLASSIFICATION_COMMON_STOCK"
            if decision is Decision.PASS
            else "CLASSIFICATION_EXCLUDED_ETF"
        ),
        evidence=(),
    )


def _classification_evidence(reference: EvidenceReference) -> SecurityClassificationEvidence:
    return SecurityClassificationEvidence(
        normalized_class="COMMON_STOCK",
        provider="APPROVED_SECURITY_MASTER",
        provider_value="Common Stock",
        observed_at_utc=UTC_NOW,
        source_version="security-master/2026-08-16",
        source_record_sha256=SHA,
        confidence="AUTHORITATIVE",
        notes="Explicit subtype evidence.",
        reference=reference,
        verified_by=None,
    )


def _normalized(
    decision: Decision = Decision.PASS, reason: str = "IDENTITY_VERIFIED"
) -> NormalizedPrerequisiteDecision:
    return NormalizedPrerequisiteDecision(decision, reason, (_reference(),))


def _prerequisites(**changes: object) -> SecurityEvaluationPrerequisites:
    values: dict[str, object] = {
        "stock_id": "1001",
        "futu_code": "US.AAPL",
        "active_status": _normalized(Decision.PASS, "ACTIVE"),
        "identity": _normalized(Decision.PASS, "IDENTITY_VERIFIED"),
    }
    values.update(changes)
    return SecurityEvaluationPrerequisites(**values)  # type: ignore[arg-type]


def _decision(result, field_id: str):
    return next(item for item in result.field_decisions if item.field_id == field_id)


def _profile_with_upper_bounds() -> object:
    profile = core_v1()
    return replace(
        profile,
        record_state=RecordState.DRAFT,
        published_at_utc=None,
        content_sha256=None,
        filter_content_sha256=None,
        filters=replace(
            profile.filters,
            min_price_usd=None,
            max_price_usd=Decimal("10.00"),
            min_market_cap_usd=None,
            max_market_cap_usd=Decimal("2000000000.00"),
        ),
    )


def test_all_core_boundaries_pass_and_keep_fixed_s1_to_s9_order() -> None:
    result = evaluate_security(core_v1(), _evidence(), _classification(), _prerequisites())

    assert tuple(item.field_id for item in result.field_decisions) == (
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
    assert all(item.decision is Decision.PASS for item in result.field_decisions)
    assert result.first_exit_stage is None
    assert result.is_member is True
    assert result.is_quarantined is False


@pytest.mark.parametrize(
    ("evidence_changes", "classification", "field_id"),
    (
        ({"exchange_raw": "OTC"}, _classification(), "S2_EXCHANGE_ALLOWED"),
        ({}, _classification(Decision.FAIL), "S3_SECURITY_CLASS_ALLOWED"),
        ({"price_usd": Decimal("4.99")}, _classification(), "S5_PRICE_ALLOWED"),
        ({"market_cap_usd": Decimal("999999999.99")}, _classification(), "S6_MARKET_CAP_ALLOWED"),
    ),
)
def test_explicit_non_membership_failures_are_audited_without_quarantine(
    evidence_changes: dict[str, object], classification: ClassificationResult, field_id: str
) -> None:
    result = evaluate_security(
        core_v1(), _evidence(**evidence_changes), classification, _prerequisites()
    )

    assert _decision(result, field_id).decision is Decision.FAIL
    assert result.first_exit_stage == field_id
    assert result.is_member is False
    assert result.is_quarantined is False
    assert len(result.field_decisions) == 9


@pytest.mark.parametrize("exchange", (None, "", "UNKNOWN", "NEW_MARKET"))
def test_missing_or_unrecognized_exchange_fails_closed_to_unknown_quarantine(
    exchange: str | None,
) -> None:
    result = evaluate_security(
        core_v1(), _evidence(exchange_raw=exchange), _classification(), _prerequisites()
    )

    assert _decision(result, "S2_EXCHANGE_ALLOWED").decision is Decision.UNKNOWN
    assert _decision(result, "S2_EXCHANGE_ALLOWED").reason_code == "EXCHANGE_UNKNOWN"
    assert result.is_member is False
    assert result.is_quarantined is True


@pytest.mark.parametrize("exchange", ("NYSE", "AMEX"))
def test_other_allowed_exchanges_pass(exchange: str) -> None:
    result = evaluate_security(
        core_v1(), _evidence(exchange_raw=exchange), _classification(), _prerequisites()
    )

    assert _decision(result, "S2_EXCHANGE_ALLOWED").decision is Decision.PASS


def test_s3_retains_classification_references_and_classification_provenance() -> None:
    reference = _reference("security-master://records/1001")
    classification_evidence = _classification_evidence(reference)
    classification = ClassificationResult(
        Decision.PASS,
        "COMMON_STOCK",
        "CLASSIFICATION_COMMON_STOCK",
        (classification_evidence,),
    )

    decision = _decision(
        evaluate_security(core_v1(), _evidence(), classification, _prerequisites()),
        "S3_SECURITY_CLASS_ALLOWED",
    )

    assert decision.evidence_references == (reference,)
    assert decision.evidence_source == "APPROVED_SECURITY_MASTER"
    assert decision.evidence_observed_at_utc == UTC_NOW
    assert decision.evidence_version == "security-master/2026-08-16"


@pytest.mark.parametrize(
    ("prerequisites", "field_id", "reason_code"),
    (
        (None, "S1_IDENTITY_VALID", "UNIVERSE_IDENTITY_BLOCKER"),
        (_prerequisites(identity=None), "S1_IDENTITY_VALID", "UNIVERSE_IDENTITY_BLOCKER"),
        (_prerequisites(active_status=None), "S4_ACTIVE_STATUS_ALLOWED", "ACTIVE_STATUS_UNKNOWN"),
        (
            _prerequisites(identity=_normalized(Decision.UNKNOWN, "UNIVERSE_IDENTITY_BLOCKER")),
            "S1_IDENTITY_VALID",
            "UNIVERSE_IDENTITY_BLOCKER",
        ),
        (
            _prerequisites(active_status=_normalized(Decision.UNKNOWN, "ACTIVE_STATUS_UNKNOWN")),
            "S4_ACTIVE_STATUS_ALLOWED",
            "ACTIVE_STATUS_UNKNOWN",
        ),
        (_prerequisites(stock_id="other"), "S1_IDENTITY_VALID", "UNIVERSE_IDENTITY_BLOCKER"),
    ),
)
def test_missing_unknown_or_mismatched_prerequisites_fail_closed_to_quarantine(
    prerequisites: SecurityEvaluationPrerequisites | None, field_id: str, reason_code: str
) -> None:
    result = evaluate_security(core_v1(), _evidence(), _classification(), prerequisites)

    decision = _decision(result, field_id)
    assert decision.decision is Decision.UNKNOWN
    assert decision.reason_code == reason_code
    assert result.is_member is False
    assert result.is_quarantined is True


def test_s1_and_s4_project_normalized_contract_verbatim() -> None:
    identity = _normalized(Decision.FAIL, "IDENTITY_CONFLICT")
    active = _normalized(Decision.FAIL, "DELISTED")
    result = evaluate_security(
        core_v1(),
        _evidence(delisting=None, suspension=None, security_status_raw="any raw enum"),
        _classification(),
        _prerequisites(identity=identity, active_status=active),
    )

    assert _decision(result, "S1_IDENTITY_VALID").decision is Decision.FAIL
    assert _decision(result, "S1_IDENTITY_VALID").reason_code == "IDENTITY_CONFLICT"
    assert _decision(result, "S1_IDENTITY_VALID").evidence_references == identity.evidence_references
    assert _decision(result, "S4_ACTIVE_STATUS_ALLOWED").decision is Decision.FAIL
    assert _decision(result, "S4_ACTIVE_STATUS_ALLOWED").reason_code == "DELISTED"
    assert _decision(result, "S4_ACTIVE_STATUS_ALLOWED").evidence_references == active.evidence_references


def test_suspended_normalized_active_prerequisite_projects_fail_verbatim() -> None:
    active = _normalized(Decision.FAIL, "SUSPENDED_AS_OF_SNAPSHOT")
    result = evaluate_security(
        core_v1(), _evidence(), _classification(), _prerequisites(active_status=active)
    )

    decision = _decision(result, "S4_ACTIVE_STATUS_ALLOWED")
    assert decision.decision is Decision.FAIL
    assert decision.reason_code == "SUSPENDED_AS_OF_SNAPSHOT"
    assert decision.evidence_references == active.evidence_references


def test_listing_liquidity_and_all_sector_behave_as_frozen() -> None:
    baseline = _evidence()
    result = evaluate_security(
        core_v1(),
        replace(
            baseline,
            listing_history=replace(baseline.listing_history, listed_days=249),
            liquidity=replace(baseline.liquidity, avg_turnover_20d_usd=Decimal("19999999.99")),
            raw_industry=RawIndustryEvidence(None, baseline.provenance),
        ),
        _classification(),
        _prerequisites(),
    )

    assert _decision(result, "S7_SECTOR_INDUSTRY_ALLOWED").decision is Decision.PASS
    assert _decision(result, "S8_LISTING_HISTORY_ALLOWED").decision is Decision.FAIL
    assert _decision(result, "S9_LIQUIDITY_ALLOWED").decision is Decision.FAIL
    assert result.first_exit_stage == "S8_LISTING_HISTORY_ALLOWED"


@pytest.mark.parametrize(
    ("kind", "field_id"),
    (
        ("listing", "S8_LISTING_HISTORY_ALLOWED"),
        ("liquidity", "S9_LIQUIDITY_ALLOWED"),
    ),
)
def test_missing_required_listing_or_liquidity_is_unknown_and_quarantined(
    kind: str, field_id: str
) -> None:
    baseline = _evidence()
    if kind == "listing":
        evidence = replace(
            baseline, listing_history=replace(baseline.listing_history, listed_days=None)
        )
    else:
        evidence = replace(
            baseline,
            liquidity=replace(baseline.liquidity, avg_turnover_20d_usd=None),
        )
    result = evaluate_security(core_v1(), evidence, _classification(), _prerequisites())

    assert _decision(result, field_id).decision is Decision.UNKNOWN
    assert result.is_quarantined is True


def test_auxiliary_listing_date_never_replaces_authoritative_listed_days() -> None:
    baseline = _evidence()
    evidence = replace(
        baseline,
        listing_history=replace(baseline.listing_history, listing_date=None, listed_days=250),
    )
    result = evaluate_security(core_v1(), evidence, _classification(), _prerequisites())

    assert _decision(result, "S8_LISTING_HISTORY_ALLOWED").decision is Decision.PASS


@pytest.mark.parametrize(
    ("price", "market_cap", "expected_field"),
    (
        (Decimal("10.00"), Decimal("2000000000.00"), None),
        (Decimal("10.01"), Decimal("2000000000.00"), "S5_PRICE_ALLOWED"),
        (Decimal("10.00"), Decimal("2000000000.01"), "S6_MARKET_CAP_ALLOWED"),
    ),
)
def test_custom_upper_bounds_are_audited_at_exact_boundary_and_beyond(
    price: Decimal, market_cap: Decimal, expected_field: str | None
) -> None:
    result = evaluate_security(
        _profile_with_upper_bounds(),  # type: ignore[arg-type]
        _evidence(price_usd=price, market_cap_usd=market_cap),
        _classification(),
        _prerequisites(),
    )

    if expected_field is None:
        assert _decision(result, "S5_PRICE_ALLOWED").operator == "<="
        assert _decision(result, "S5_PRICE_ALLOWED").threshold == Decimal("10.00")
        assert _decision(result, "S6_MARKET_CAP_ALLOWED").operator == "<="
        assert _decision(result, "S6_MARKET_CAP_ALLOWED").threshold == Decimal("2000000000.00")
        assert result.is_member is True
    else:
        assert _decision(result, expected_field).decision is Decision.FAIL
        assert _decision(result, expected_field).operator == "<="


@pytest.mark.parametrize("field_id", ("S5_PRICE_ALLOWED", "S6_MARKET_CAP_ALLOWED"))
def test_missing_price_or_market_cap_is_unknown_and_quarantined(field_id: str) -> None:
    changes = {"price_usd": None} if field_id == "S5_PRICE_ALLOWED" else {"market_cap_usd": None}
    result = evaluate_security(core_v1(), _evidence(**changes), _classification(), _prerequisites())

    assert _decision(result, field_id).decision is Decision.UNKNOWN
    assert result.is_quarantined is True


@pytest.mark.parametrize("kind", ("listing", "liquidity"))
def test_metric_or_version_mismatch_is_unknown_and_quarantined(kind: str) -> None:
    baseline = _evidence()
    if kind == "listing":
        evidence = replace(
            baseline,
            listing_history=replace(baseline.listing_history, evidence_version="other/v1"),
        )
        field_id = "S8_LISTING_HISTORY_ALLOWED"
    else:
        evidence = replace(
            baseline,
            liquidity=replace(baseline.liquidity, metric_id="OTHER_ADV20"),
        )
        field_id = "S9_LIQUIDITY_ALLOWED"

    result = evaluate_security(core_v1(), evidence, _classification(), _prerequisites())

    assert _decision(result, field_id).decision is Decision.UNKNOWN
    assert result.is_quarantined is True


@pytest.mark.parametrize(
    ("kind", "reason", "field_id"),
    (
        ("listing", "LISTING_HISTORY_CONFLICT", "S8_LISTING_HISTORY_ALLOWED"),
        ("liquidity", "LIQUIDITY_EVIDENCE_CONFLICT", "S9_LIQUIDITY_ALLOWED"),
    ),
)
def test_authoritative_evidence_conflicts_are_unknown_and_quarantined(
    kind: str, reason: str, field_id: str
) -> None:
    baseline = _evidence()
    if kind == "listing":
        evidence = replace(
            baseline,
            listing_history=replace(baseline.listing_history, reason_codes=(reason,)),
        )
    else:
        evidence = replace(
            baseline,
            liquidity=replace(baseline.liquidity, reason_codes=(reason,)),
        )
    result = evaluate_security(core_v1(), evidence, _classification(), _prerequisites())

    assert _decision(result, field_id).decision is Decision.UNKNOWN
    assert _decision(result, field_id).reason_code == reason
    assert result.is_quarantined is True


def test_classification_conflict_remains_unknown_and_quarantined_in_evaluator() -> None:
    classification = ClassificationResult(
        Decision.UNKNOWN, "UNKNOWN", "CLASSIFICATION_EVIDENCE_CONFLICT", ()
    )
    result = evaluate_security(core_v1(), _evidence(), classification, _prerequisites())

    assert _decision(result, "S3_SECURITY_CLASS_ALLOWED").decision is Decision.UNKNOWN
    assert result.is_quarantined is True


def test_observed_at_is_audit_provenance_and_never_a_freshness_decision() -> None:
    baseline = _evidence()
    old_provenance = replace(baseline.provenance, observed_at_utc=datetime(2000, 1, 1, tzinfo=timezone.utc))
    result = evaluate_security(
        core_v1(), replace(baseline, provenance=old_provenance), _classification(), _prerequisites()
    )

    decision = _decision(result, "S5_PRICE_ALLOWED")
    assert decision.decision is Decision.PASS
    assert decision.evidence_observed_at_utc == old_provenance.observed_at_utc


@pytest.mark.parametrize(
    ("authoritative", "cross_check", "decision", "reason"),
    (
        ("20000000.004", "20000000.005", Decision.PASS, "LIQUIDITY_CROSS_CHECK_MATCH"),
        ("20000000.004", "20000000.006", Decision.PASS, "LIQUIDITY_CROSS_CHECK_MATCH"),
        ("20000000.00", "20000000.02", Decision.UNKNOWN, "LIQUIDITY_EVIDENCE_CONFLICT"),
        ("NaN", "20000000.00", Decision.UNKNOWN, "LIQUIDITY_CROSS_CHECK_INVALID"),
    ),
)
def test_liquidity_cross_check_uses_decimal_half_even_and_absolute_cent_tolerance(
    authoritative: str, cross_check: str, decision: Decision, reason: str
) -> None:
    result = compare_liquidity_cross_check(authoritative, cross_check)

    assert result.decision is decision
    assert result.reason_code == reason


def test_liquidity_cross_check_preserves_half_even_fifteen_millis() -> None:
    result = compare_liquidity_cross_check("0.015", "0.015")

    assert result.decision is Decision.PASS
    assert result.normalized_value == (Decimal("0.02"), Decimal("0.02"))


@pytest.mark.parametrize("invalid", ("-0.01", "Infinity", "", "NaN"))
def test_liquidity_cross_check_rejects_invalid_source_strings(invalid: str) -> None:
    result = compare_liquidity_cross_check(invalid, "20000000.00")

    assert result.decision is Decision.UNKNOWN
    assert result.reason_code == "LIQUIDITY_CROSS_CHECK_INVALID"


def test_prerequisite_contract_is_immutable_sorted_and_rejects_invalid_pass() -> None:
    second = _reference("futu://screening/US.AAPL?page=2")
    decision = NormalizedPrerequisiteDecision(
        Decision.PASS, "ACTIVE", (second, _reference())
    )

    assert decision.evidence_references == (_reference(), second)
    with pytest.raises(FrozenInstanceError):
        decision.reason_code = "CHANGED"  # type: ignore[misc]
    with pytest.raises(ValueError, match="references"):
        NormalizedPrerequisiteDecision(Decision.FAIL, "DELISTED", ())
    with pytest.raises(ValueError, match="decision"):
        NormalizedPrerequisiteDecision(Decision.NOT_APPLICABLE, "NOPE", ())


def test_manual_security_evaluation_cannot_lie_about_membership_or_quarantine() -> None:
    passing = evaluate_security(core_v1(), _evidence(), _classification(), _prerequisites())
    unknown = evaluate_security(
        core_v1(), _evidence(exchange_raw="UNKNOWN"), _classification(), _prerequisites()
    )

    with pytest.raises(ValueError, match="membership"):
        replace(passing, is_member=False)
    with pytest.raises(ValueError, match="membership"):
        replace(passing, is_quarantined=True)
    with pytest.raises(ValueError, match="membership"):
        replace(unknown, is_member=True, is_quarantined=False)


def test_evaluator_ast_has_no_provider_status_or_runtime_dependency_boundaries() -> None:
    path = Path(__file__).parents[3] / "src" / "tv_quant" / "pattern_finder" / "universe_foundation" / "evaluator.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert not {"security_status_raw", "delisting", "suspension", "datetime", "time", "Path"} & (names | attributes)
    assert not {
        "ledger", "now", "today", "open", "provider_update_time", "market_data_delay_class",
        "calendar", "timedelta", "utcnow", "ticker",
    } & (names | attributes)
    evaluator_function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_security"
    )
    assert not any(
        isinstance(node, (ast.For, ast.AsyncFor, ast.While))
        for node in ast.walk(evaluator_function)
    )
    assert not any(
        any(blocked in name.lower() for blocked in ("futu", "detector", "streamlit", "gateway", "pathlib", "os", "sqlite", "requests", "http"))
        for name in imported
    )
