from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from tv_quant.pattern_finder.universe_foundation import (
    ClassificationResult,
    Decision,
    EvidenceProvenance,
    EvidenceReference,
    LiquidityEvidence,
    ListingHistoryEvidence,
    NormalizedPrerequisiteDecision,
    ProfileRegistry,
    RawIndustryEvidence,
    RecordState,
    SecurityEvaluationPrerequisites,
    UniverseSecurityEvidence,
    core_v1,
)
from tv_quant.pattern_finder.universe_foundation import ui_read_model
from tv_quant.pattern_finder.universe_foundation.ui_read_model import (
    build_evaluation_ui_state,
    load_profile_ui_state,
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


def _evidence() -> UniverseSecurityEvidence:
    provenance = _provenance()
    return UniverseSecurityEvidence(
        schema_version="universe-security-evidence/v1",
        stock_id="1001",
        futu_code="US.AAPL",
        symbol="AAPL",
        name="Apple Inc.",
        exchange_raw="NASDAQ",
        security_type_raw="STOCK",
        delisting=None,
        suspension=None,
        security_status_raw=None,
        price_usd=Decimal("5.00"),
        market_cap_usd=Decimal("1000000000.00"),
        provenance=provenance,
        raw_industry=RawIndustryEvidence("Technology", provenance),
        raw_plates=(),
        classification_evidence=(),
        liquidity=LiquidityEvidence(
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
        listing_history=ListingHistoryEvidence(
            metric_id="FUTU_LISTED_DAYS",
            evidence_version="futu-screening-listing-history/v1",
            listed_days=250,
            listing_date=date(1980, 12, 12),
            raw_value="250",
            provenance=provenance,
            reason_codes=(),
        ),
        reason_codes=(),
    )


def _classification() -> ClassificationResult:
    return ClassificationResult(
        decision=Decision.PASS,
        normalized_class="COMMON_STOCK",
        reason_code="CLASSIFICATION_COMMON_STOCK",
        evidence=(),
    )


def _prerequisites(
    *, identity: Decision = Decision.PASS
) -> SecurityEvaluationPrerequisites:
    return SecurityEvaluationPrerequisites(
        stock_id="1001",
        futu_code="US.AAPL",
        active_status=NormalizedPrerequisiteDecision(
            Decision.PASS, "ACTIVE", (_reference("futu://snapshot/US.AAPL"),)
        ),
        identity=NormalizedPrerequisiteDecision(
            identity,
            "IDENTITY_VERIFIED" if identity is Decision.PASS else "UNIVERSE_IDENTITY_BLOCKER",
            (_reference("futu://identity/US.AAPL"),),
        ),
    )


def _registry_containing_only_draft_core_v1(tmp_path) -> ProfileRegistry:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())
    published_path = tmp_path / "published.jsonl"
    payload = json.loads(published_path.read_text(encoding="utf-8"))
    payload["record_state"] = "DRAFT"
    published_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    return registry


def test_load_profile_ui_state_renders_initialized_published_core_v1(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)
    registry.bootstrap(core_v1())

    state = load_profile_ui_state(registry, "CORE:v1")

    assert state.profile_version_id == "CORE:v1"
    assert state.display_name == "CORE v1"
    assert state.record_state == "PUBLISHED"
    assert state.published_at_utc == datetime(2026, 8, 11, tzinfo=timezone.utc)
    assert state.change_note == "Frozen default US common-stock universe."
    assert state.content_sha256 == core_v1().content_sha256
    assert state.filter_content_sha256 == core_v1().filter_content_sha256
    assert tuple((row.label, row.value) for row in state.conditions) == (
        ("Exchanges", "AMEX, NASDAQ, NYSE"),
        ("Allowed security classes", "COMMON_STOCK"),
        ("Minimum price (USD)", "5.00"),
        ("Maximum price (USD)", "None"),
        ("Minimum market cap (USD)", "1000000000.00"),
        ("Maximum market cap (USD)", "None"),
        ("Liquidity metric", "FUTU_AVG_TURNOVER_20D"),
        ("Liquidity evidence version", "futu-screening-liquidity/v1"),
        ("Minimum average dollar volume, 20D (USD)", "20000000.00"),
        ("Minimum average volume, 20D (shares)", "None"),
        ("Listing history metric", "FUTU_LISTED_DAYS"),
        ("Listing history evidence version", "futu-screening-listing-history/v1"),
        ("Minimum listed days", "250"),
        ("Sectors", "ALL"),
        ("Industries", "ALL"),
        ("Sector mapping version", "None"),
        ("Include ETF", "False"),
        ("Include ADR", "False"),
        ("Include OTC", "False"),
        ("Include preferred", "False"),
        ("Include warrant", "False"),
        ("Include unit", "False"),
        ("Active only", "True"),
    )


def test_load_profile_ui_state_rejects_empty_registry_without_bootstrap(tmp_path) -> None:
    registry = ProfileRegistry(tmp_path)

    with pytest.raises(RuntimeError, match="not initialized: CORE:v1"):
        load_profile_ui_state(registry, "CORE:v1")

    assert registry.list_published() == ()


def test_load_profile_ui_state_rejects_non_published_profile_as_current(tmp_path) -> None:
    registry = _registry_containing_only_draft_core_v1(tmp_path)

    assert registry.get_published("CORE:v1").record_state is RecordState.DRAFT
    with pytest.raises(RuntimeError, match="no current published profile: CORE:v1"):
        load_profile_ui_state(registry, "CORE:v1")


def test_build_evaluation_ui_state_projects_the_single_task6_pass_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = core_v1()
    evidence = _evidence()
    classification = _classification()
    prerequisites = _prerequisites()
    calls: list[tuple[object, object, object, object]] = []
    original = ui_read_model.evaluate_security

    def _evaluate_once(*args, **kwargs):
        calls.append((args[0], args[1], args[2], args[3]))
        return original(*args, **kwargs)

    monkeypatch.setattr(ui_read_model, "evaluate_security", _evaluate_once)

    state = build_evaluation_ui_state(
        profile=profile,
        evidence=evidence,
        classification=classification,
        prerequisites=prerequisites,
    )

    assert calls == [(profile, evidence, classification, prerequisites)]
    assert (state.stock_id, state.futu_code, state.symbol, state.name) == (
        "1001",
        "US.AAPL",
        "AAPL",
        "Apple Inc.",
    )
    assert state.profile_version_id == "CORE:v1"
    assert state.profile_content_sha256 == core_v1().content_sha256
    assert state.is_member is True
    assert state.is_quarantined is False
    assert state.first_exit_stage is None
    assert state.first_exit_reason_code is None
    assert len(state.decisions) == 9
    price = next(item for item in state.decisions if item.field_id == "S5_PRICE_ALLOWED")
    assert price.decision == "PASS"
    assert price.actual_value == "5.00"
    assert price.normalized_value == "5.00"
    assert price.operator == ">="
    assert price.threshold == "5.00"
    assert price.reason_code == "WITHIN_BOUNDS"
    assert price.evidence_source == "FUTU"
    assert price.evidence_references == ("FUTU: futu://screening/US.AAPL",)
    assert price.evidence_version == "opend/9.4"


def test_build_evaluation_ui_state_projects_unknown_identity_as_quarantine() -> None:
    state = build_evaluation_ui_state(
        profile=core_v1(),
        evidence=_evidence(),
        classification=_classification(),
        prerequisites=_prerequisites(identity=Decision.UNKNOWN),
    )

    identity = state.decisions[0]
    assert state.is_member is False
    assert state.is_quarantined is True
    assert state.first_exit_stage == "S1_IDENTITY_VALID"
    assert state.first_exit_reason_code == "UNIVERSE_IDENTITY_BLOCKER"
    assert identity.decision == "UNKNOWN"
    assert identity.reason_code == "UNIVERSE_IDENTITY_BLOCKER"
    assert identity.evidence_source is None
    assert identity.evidence_references == ("FUTU: futu://identity/US.AAPL",)
