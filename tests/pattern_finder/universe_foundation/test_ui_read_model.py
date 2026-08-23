from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from tv_quant.pattern_finder.universe_foundation import (
    ActiveStatusMappingEntry,
    ApiBatchRecord,
    AttemptStatus,
    ClassificationResult,
    Completeness,
    Decision,
    EvidenceProvenance,
    EvidenceReference,
    GatewayAttempt,
    GatewayPreflight,
    IdentityLedgerEntry,
    LiquidityEvidence,
    ListingHistoryEvidence,
    NormalizedPrerequisiteDecision,
    ProfileKind,
    ProfileRegistry,
    QualifiedActiveStatusMapping,
    QualifiedMarketStateConsistencyContract,
    QualifiedMarketStateRelationship,
    RawIndustryEvidence,
    RawApiBatch,
    RawPlateEvidence,
    RecordState,
    SecurityClassificationEvidence,
    SecurityEvaluationPrerequisites,
    UniverseSecurityEvidence,
    SnapshotCorruptError,
    SnapshotKind,
    SnapshotNotFoundError,
    SnapshotValidationError,
    UniverseSnapshotStore,
    build_funnel,
    build_snapshot,
    core_v1,
    evaluate_security,
    prerequisites_sha256,
)
from tv_quant.pattern_finder.universe_foundation import ui_read_model
from tv_quant.pattern_finder.universe_foundation.ui_read_model import (
    build_evaluation_ui_state,
    find_security_decision,
    load_profile_ui_state,
    load_snapshot_ui_state,
    snapshot_ui_download_json,
)


UTC_NOW = datetime(2026, 8, 16, 12, 0, tzinfo=timezone.utc)
SHA = "a" * 64
SNAPSHOT_ID = __import__("uuid").UUID("12121212-1212-4212-8212-121212121212")


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


def _classification_evidence(
    normalized_class: str = "COMMON_STOCK",
) -> tuple[SecurityClassificationEvidence, ...]:
    reference = _reference("openfigi://classification/AAPL")
    return (
        SecurityClassificationEvidence(
            normalized_class=normalized_class,
            provider="OPENFIGI",
            provider_value="Common Stock" if normalized_class == "COMMON_STOCK" else "",
            observed_at_utc=UTC_NOW,
            source_version="openfigi-api/v3",
            source_record_sha256=SHA,
            confidence="CORROBORATED",
            notes="persisted fixture evidence",
            reference=reference,
            verified_by=None,
        ),
    ) if normalized_class != "UNKNOWN" else ()


def _snapshot_evidence(
    symbol: str,
    *,
    liquidity_reasons: tuple[str, ...] = (),
    listing_reasons: tuple[str, ...] = (),
) -> UniverseSecurityEvidence:
    code = f"US.{symbol}"
    provenance = EvidenceProvenance(
        provider="FUTU",
        provider_version="10.10.7008",
        source_version="1009",
        schema_version="futu-screening/v2",
        observed_at_utc=UTC_NOW,
        references=(_reference(f"futu://screening/{code}"),),
    )
    return UniverseSecurityEvidence(
        schema_version="universe-security-evidence/v1",
        stock_id=f"stock-{symbol}",
        futu_code=code,
        symbol=symbol,
        name=f"{symbol} Incorporated",
        exchange_raw="NASDAQ",
        security_type_raw="STOCK",
        delisting=False,
        suspension=False,
        security_status_raw="NORMAL",
        price_usd=Decimal("5.00"),
        market_cap_usd=Decimal("1000000000.00"),
        provenance=provenance,
        raw_industry=RawIndustryEvidence("Technology Hardware", provenance),
        raw_plates=(
            RawPlateEvidence("PLATE-TECH", "Technology", "INDUSTRY", provenance),
            RawPlateEvidence("PLATE-NDX", "NASDAQ 100", "INDEX", provenance),
        ),
        classification_evidence=_classification_evidence(),
        liquidity=LiquidityEvidence(
            metric_id="FUTU_AVG_TURNOVER_20D",
            evidence_version="futu-screening-liquidity/v1",
            avg_turnover_20d_usd=Decimal("20000000.00"),
            avg_volume_20d_shares=Decimal("4000000"),
            window_days=20,
            currency="USD",
            raw_value="20000000.00",
            provenance=provenance,
            reason_codes=liquidity_reasons,
        ),
        listing_history=ListingHistoryEvidence(
            metric_id="FUTU_LISTED_DAYS",
            evidence_version="futu-screening-listing-history/v1",
            listed_days=250,
            listing_date=None if "LISTING_DATE_AUXILIARY_INVALID" in listing_reasons else date(2020, 1, 2),
            raw_value="250",
            provenance=provenance,
            reason_codes=listing_reasons,
        ),
        reason_codes=(),
    )


def _snapshot_prerequisite(
    evidence: UniverseSecurityEvidence,
    *,
    identity: Decision = Decision.PASS,
    active: Decision = Decision.PASS,
) -> SecurityEvaluationPrerequisites:
    reference = evidence.provenance.references[0]
    identity_reasons = {
        Decision.PASS: "IDENTITY_RECONCILED",
        Decision.FAIL: "IDENTITY_REJECTED",
        Decision.UNKNOWN: "UNIVERSE_IDENTITY_BLOCKER",
    }
    active_reasons = {
        Decision.PASS: "ACTIVE_ALLOWED",
        Decision.FAIL: "DELISTED",
        Decision.UNKNOWN: "ACTIVE_STATUS_UNKNOWN",
    }
    return SecurityEvaluationPrerequisites(
        stock_id=evidence.stock_id,
        futu_code=evidence.futu_code,
        active_status=NormalizedPrerequisiteDecision(
            active, active_reasons[active], (reference,)
        ),
        identity=NormalizedPrerequisiteDecision(
            identity, identity_reasons[identity], (reference,)
        ),
    )


def _snapshot_attempt(
    evidence: tuple[UniverseSecurityEvidence, ...],
    prerequisites: tuple[SecurityEvaluationPrerequisites, ...],
    *,
    incomplete: bool = False,
) -> GatewayAttempt:
    qualification = EvidenceReference(
        "qualification", "futu://qualification/active/v1", SHA
    )
    mapping = QualifiedActiveStatusMapping(
        provider="FUTU",
        provider_sdk_version="10.10.7008",
        opend_server_version="1009",
        mapping_version="active/v1",
        entries=(ActiveStatusMappingEntry("NORMAL", Decision.PASS, "ACTIVE_ALLOWED"),),
        qualified_at_utc=UTC_NOW,
        qualification_references=(qualification,),
    )
    market_contract = QualifiedMarketStateConsistencyContract(
        provider="FUTU",
        provider_sdk_version="10.10.7008",
        opend_server_version="1009",
        mapping_version="market-state-consistency/after-hours-end-v1",
        qualified_at_utc=UTC_NOW,
        qualification_references=(qualification,),
        qualified_relationships=(
            QualifiedMarketStateRelationship("AFTER_HOURS_END", "XNYS_NON_SESSION"),
        ),
    )
    reasons = ("UNIVERSE_INCOMPLETE_BLOCKER",) if incomplete else ()
    identity_reference = evidence[0].provenance.references[0]
    return GatewayAttempt(
        attempt_id="attempt-task-12-incomplete" if incomplete else "attempt-task-12",
        as_of_session=date(2026, 8, 15),
        observed_at_utc=UTC_NOW,
        provider_update_time=UTC_NOW,
        runtime_evidence_window_seconds=0.0,
        market_data_delay_class="DELAYED",
        market_state_consistency_contract=market_contract,
        active_status_mapping=mapping,
        prerequisites_sha256=prerequisites_sha256(prerequisites),
        preflight=GatewayPreflight(
            provider="FUTU",
            provider_sdk_version="10.10.7008",
            opend_server_version="1009",
            as_of_session=date(2026, 8, 15),
            observed_at_utc=UTC_NOW,
            provider_update_time=UTC_NOW,
            market_data_delay_class="DELAYED",
            formal_ready=not incomplete,
            reason_codes=reasons,
        ),
        evidence=evidence,
        prerequisites=prerequisites,
        batches=(ApiBatchRecord("qot_right_capture", 1, SHA, "b" * 64, UTC_NOW),),
        identity_ledger=(
            IdentityLedgerEntry(
                evidence[0].stock_id,
                evidence[0].futu_code,
                Decision.PASS,
                "IDENTITY_RECONCILED",
                (evidence[0].stock_id,),
                (evidence[0].futu_code,),
                (identity_reference,),
                reconciliation_completed=True,
            ),
        ),
        attempt_status=AttemptStatus.FAILED if incomplete else AttemptStatus.SUCCEEDED,
        completeness=Completeness.INCOMPLETE if incomplete else Completeness.COMPLETE,
        reason_codes=reasons,
        realtime_capability_probes=(
            RawApiBatch(
                endpoint="realtime_quote_capability_probe",
                batch_index=1,
                raw_request={
                    "code": evidence[0].futu_code,
                    "subtype": "QUOTE",
                    "subscribe_push": False,
                },
                raw_response={"ret_code": 0, "rows": [{"code": evidence[0].futu_code}]},
                request_hash=SHA,
                response_hash="b" * 64,
                ret_code=0,
                acquisition_status="SUCCESS",
                acquired_at_utc=UTC_NOW,
            ),
        ),
    )


def _persist_complete_snapshot(tmp_path) -> tuple[UniverseSnapshotStore, object]:
    cases = (
        (_snapshot_evidence("BOUND", listing_reasons=("LISTING_DATE_AUXILIARY_INVALID",)), Decision.PASS, Decision.PASS, Decision.PASS),
        (_snapshot_evidence("IDFAIL"), Decision.FAIL, Decision.PASS, Decision.PASS),
        (_snapshot_evidence("IDUNK"), Decision.UNKNOWN, Decision.PASS, Decision.PASS),
        (_snapshot_evidence("ACTIVEFAIL"), Decision.PASS, Decision.FAIL, Decision.PASS),
        (_snapshot_evidence("ACTIVEUNK"), Decision.PASS, Decision.UNKNOWN, Decision.PASS),
        (_snapshot_evidence("CLASSUNK"), Decision.PASS, Decision.PASS, Decision.UNKNOWN),
        (_snapshot_evidence("CONFLICT", liquidity_reasons=("LIQUIDITY_EVIDENCE_CONFLICT",), listing_reasons=("LISTING_HISTORY_CONFLICT",)), Decision.PASS, Decision.PASS, Decision.PASS),
    )
    evidence = tuple(case[0] for case in cases)
    prerequisites = tuple(
        _snapshot_prerequisite(case[0], identity=case[1], active=case[2])
        for case in cases
    )
    classifications = tuple(
        ClassificationResult(
            decision=case[3],
            normalized_class="COMMON_STOCK" if case[3] is Decision.PASS else "UNKNOWN",
            reason_code="CLASSIFICATION_COMMON_STOCK" if case[3] is Decision.PASS else "CLASSIFICATION_UNKNOWN",
            evidence=case[0].classification_evidence if case[3] is Decision.PASS else (),
        )
        for case in cases
    )
    evaluations = tuple(
        evaluate_security(core_v1(), item, classification, prerequisite)
        for item, classification, prerequisite in zip(evidence, classifications, prerequisites)
    )
    attempt = _snapshot_attempt(evidence, prerequisites)
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=SNAPSHOT_ID,
        created_at_utc=UTC_NOW,
    )
    store = UniverseSnapshotStore(tmp_path)
    return store, store.append(snapshot)


def _persist_incomplete_snapshot(tmp_path) -> tuple[UniverseSnapshotStore, object]:
    evidence = (_snapshot_evidence("INCOMPLETE"),)
    prerequisites = (_snapshot_prerequisite(evidence[0]),)
    classification = ClassificationResult(
        Decision.PASS,
        "COMMON_STOCK",
        "CLASSIFICATION_COMMON_STOCK",
        evidence[0].classification_evidence,
    )
    evaluations = (
        evaluate_security(core_v1(), evidence[0], classification, prerequisites[0]),
    )
    registry = ProfileRegistry(tmp_path / "registry")
    registry.bootstrap(core_v1())
    draft = registry.create_draft(
        draft_id="draft-task-12",
        family_id="CORE",
        profile_kind=ProfileKind.CORE,
        display_name="CORE Task 12 preview",
        change_note="Persisted incomplete projection fixture.",
        source_profile_version_id="CORE:v1",
        created_at_utc=UTC_NOW,
    )
    snapshot = build_snapshot(
        kind=SnapshotKind.PREVIEW,
        profile=None,
        draft=draft,
        gateway_attempt=_snapshot_attempt(evidence, prerequisites, incomplete=True),
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=__import__("uuid").UUID(
            "13131313-1313-4313-8313-131313131313"
        ),
        created_at_utc=UTC_NOW,
    )
    store = UniverseSnapshotStore(tmp_path / "snapshots")
    return store, store.append(snapshot)


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


def test_load_snapshot_ui_state_projects_persisted_complete_audit_contract(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, persisted = _persist_complete_snapshot(tmp_path)
    calls: list[object] = []
    original_get = UniverseSnapshotStore.get

    def _get_once(self, snapshot_id):
        calls.append(snapshot_id)
        return original_get(self, snapshot_id)

    monkeypatch.setattr(UniverseSnapshotStore, "get", _get_once)
    monkeypatch.setattr(
        ui_read_model,
        "evaluate_security",
        lambda *args, **kwargs: pytest.fail("snapshot projection called evaluator"),
    )

    state = load_snapshot_ui_state(store, SNAPSHOT_ID)

    assert calls == [SNAPSHOT_ID]
    assert state.snapshot_id == str(SNAPSHOT_ID)
    assert state.snapshot_schema_version == "universe-snapshot/v1"
    assert state.snapshot_kind == "FORMAL"
    assert state.completeness == "COMPLETE"
    assert state.profile_version_id == "CORE:v1"
    assert state.profile_content_sha256 == core_v1().content_sha256
    assert state.draft_id is None
    assert state.gateway_attempt_id == "attempt-task-12"
    assert state.gateway_preflight_as_of_session == "2026-08-15"
    assert state.gateway_preflight_observed_at_utc == UTC_NOW.isoformat()
    assert state.gateway_preflight_provider_update_time == UTC_NOW.isoformat()
    assert state.gateway_preflight_market_data_delay_class == "DELAYED"
    assert state.gateway_preflight_formal_ready is True
    assert state.gateway_preflight_reason_codes == ()
    assert state.gateway_runtime_evidence_window_seconds == 0.0
    assert state.gateway_attempt_sha256 == persisted.header.gateway_attempt_sha256
    assert state.provider == "FUTU"
    assert state.provider_sdk_version == "10.10.7008"
    assert state.opend_server_version == "1009"
    assert state.gateway_batches[0].endpoint == "qot_right_capture"
    assert state.gateway_batches[0].batch_index == 1
    assert state.gateway_batches[0].request_hash == SHA
    assert state.gateway_batches[0].response_hash == "b" * 64
    assert state.gateway_batches[0].acquired_at_utc == UTC_NOW.isoformat()
    assert state.gateway_identity_ledger[0].stock_id == "stock-BOUND"
    assert state.gateway_identity_ledger[0].decision == "PASS"
    assert state.gateway_identity_ledger[0].reconciliation_completed is True
    assert state.gateway_identity_ledger[0].evidence_references == (
        f"FUTU: futu://screening/US.BOUND [{SHA}]",
    )
    assert state.market_data_delay_evidence == state.gateway_batches
    assert state.realtime_capability_probes[0].endpoint == (
        "realtime_quote_capability_probe"
    )
    assert state.realtime_capability_probes[0].raw_request == {
        "code": "US.BOUND",
        "subtype": "QUOTE",
        "subscribe_push": False,
    }
    assert state.realtime_capability_probes[0].raw_response == {
        "ret_code": 0,
        "rows": [{"code": "US.BOUND"}],
    }
    assert state.realtime_capability_probes[0].ret_code == 0
    assert state.market_state_consistency_sha256 == (
        persisted.header.market_state_consistency_sha256
    )
    assert state.active_status_mapping_provider == "FUTU"
    assert state.active_status_mapping_provider_sdk_version == "10.10.7008"
    assert state.active_status_mapping_opend_server_version == "1009"
    assert state.active_status_mapping_version == "active/v1"
    assert state.active_status_mapping_qualification_references == (
        f"qualification: futu://qualification/active/v1 [{SHA}]",
    )
    assert state.active_status_mapping_sha256 == persisted.header.active_status_mapping_sha256
    assert state.prerequisites_sha256 == persisted.header.prerequisites_sha256
    assert state.sector_mapping_version is None
    assert state.liquidity_metric_id == "FUTU_AVG_TURNOVER_20D"
    assert state.liquidity_evidence_version == "futu-screening-liquidity/v1"
    assert state.listing_history_metric_id == "FUTU_LISTED_DAYS"
    assert state.listing_history_evidence_version == (
        "futu-screening-listing-history/v1"
    )
    assert state.classification_source_versions == ("openfigi-api/v3",)
    assert state.members_sha256 == persisted.header.members_sha256
    assert state.snapshot_content_sha256 == persisted.header.snapshot_content_sha256
    assert state.snapshot_record_sha256 == persisted.header.snapshot_record_sha256
    assert state.candidate_count == 7
    assert state.member_count == 1
    assert len(state.members) == 1
    assert {item.symbol for item in state.failures} == {"IDFAIL", "ACTIVEFAIL"}
    assert {item.symbol for item in state.quarantined} == {
        "ACTIVEUNK",
        "CLASSUNK",
        "CONFLICT",
        "IDUNK",
    }
    assert tuple(stage.stage_id for stage in state.funnel_stages) == tuple(
        stage.stage_id for stage in persisted.funnel.stages
    )
    assert all(
        stage.input_count
        == stage.pass_count + stage.fail_count + stage.unknown_count
        for stage in state.funnel_stages
    )

    boundary = find_security_decision(state, "bound")
    assert boundary is not None
    assert boundary.stock_id == "stock-BOUND"
    assert boundary.futu_code == "US.BOUND"
    assert boundary.symbol == "BOUND"
    assert boundary.evaluation_status == "MEMBER"
    assert boundary.is_member is True
    assert boundary.is_quarantined is False
    assert boundary.raw_industry == "Technology Hardware"
    assert tuple(item.plate_code for item in boundary.raw_plates) == (
        "PLATE-NDX",
        "PLATE-TECH",
    )
    assert boundary.listing_history_cross_check == (
        "LISTING_DATE_AUXILIARY_INVALID",
    )
    assert boundary.classification_evidence[0].normalized_class == "COMMON_STOCK"
    assert boundary.classification_evidence[0].source_version == "openfigi-api/v3"
    listing = next(item for item in boundary.decisions if item.field_id == "S8_LISTING_HISTORY_ALLOWED")
    liquidity = next(item for item in boundary.decisions if item.field_id == "S9_LIQUIDITY_ALLOWED")
    assert (listing.decision, listing.actual_value, listing.normalized_value) == (
        "PASS",
        "250",
        "250",
    )
    assert listing.threshold == "250"
    assert listing.authoritative_metric == "FUTU_LISTED_DAYS"
    assert liquidity.decision == "PASS"
    assert liquidity.actual_value == "20000000.00"
    assert liquidity.threshold == "20000000.00"
    assert liquidity.authoritative_metric == "FUTU_AVG_TURNOVER_20D"
    assert liquidity.evidence_observed_at_utc == UTC_NOW.isoformat()
    assert liquidity.evidence_references == (
        f"FUTU: futu://screening/US.BOUND [{SHA}]",
    )
    assert boundary.raw_evidence_sha256
    assert boundary.snapshot_content_sha256 == state.snapshot_content_sha256
    assert boundary.snapshot_record_sha256 == state.snapshot_record_sha256
    assert boundary.profile_version_id == "CORE:v1"
    assert boundary.members_sha256 == state.members_sha256
    assert boundary.exchange_raw == "NASDAQ"
    assert boundary.exchange_normalized == "NASDAQ"
    assert boundary.security_type_raw == "STOCK"
    assert boundary.security_class_normalized == "COMMON_STOCK"
    assert boundary.delisting is False
    assert boundary.suspension is False
    assert boundary.security_status_raw == "NORMAL"
    assert boundary.price_usd == "5.00"
    assert boundary.price_observed_at_utc == UTC_NOW.isoformat()
    assert boundary.market_cap_usd == "1000000000.00"
    assert boundary.market_cap_observed_at_utc == UTC_NOW.isoformat()
    assert boundary.liquidity_metric_id == "FUTU_AVG_TURNOVER_20D"
    assert boundary.liquidity_evidence_version == "futu-screening-liquidity/v1"
    assert boundary.avg_turnover_20d_usd == "20000000.00"
    assert boundary.liquidity_window_end == "2026-08-16"
    assert boundary.avg_volume_20d_shares == "4000000"
    assert boundary.listing_history_metric_id == "FUTU_LISTED_DAYS"
    assert boundary.listing_history_evidence_version == (
        "futu-screening-listing-history/v1"
    )
    assert boundary.listing_date is None
    assert boundary.listed_days == 250
    assert boundary.sector_mapping_version is None
    assert boundary.raw_industry_references == (
        f"FUTU: futu://screening/US.BOUND [{SHA}]",
    )
    assert boundary.raw_industry_provider_version == "10.10.7008"
    assert boundary.raw_industry_source_version == "1009"
    assert boundary.raw_industry_schema_version == "futu-screening/v2"
    assert all(item.provider_version == "10.10.7008" for item in boundary.raw_plates)
    assert all(item.source_version == "1009" for item in boundary.raw_plates)
    assert all(
        item.schema_version == "futu-screening/v2" for item in boundary.raw_plates
    )

    identity = {
        item.symbol: (item.identity_decision, item.identity_reason_code)
        for item in state.decisions
    }
    active = {
        item.symbol: (item.active_status_decision, item.active_status_reason_code)
        for item in state.decisions
    }
    assert identity["BOUND"] == ("PASS", "IDENTITY_RECONCILED")
    assert identity["IDFAIL"] == ("FAIL", "IDENTITY_REJECTED")
    assert identity["IDUNK"] == ("UNKNOWN", "UNIVERSE_IDENTITY_BLOCKER")
    assert active["BOUND"] == ("PASS", "ACTIVE_ALLOWED")
    assert active["ACTIVEFAIL"] == ("FAIL", "DELISTED")
    assert active["ACTIVEUNK"] == ("UNKNOWN", "ACTIVE_STATUS_UNKNOWN")
    assert all(item.identity_evidence_references for item in state.decisions)
    assert all(item.active_status_evidence_references for item in state.decisions)

    class_unknown = find_security_decision(state, "US.CLASSUNK")
    assert class_unknown is not None
    assert class_unknown.evaluation_status == "QUARANTINE"
    assert class_unknown.first_exit_stage == "S3_SECURITY_CLASS_ALLOWED"
    assert class_unknown.first_exit_reason_code == "CLASSIFICATION_UNKNOWN"
    conflict = find_security_decision(state, "stock-CONFLICT")
    assert conflict is not None
    assert conflict.is_quarantined is True
    assert {item.reason_code for item in conflict.decisions} >= {
        "LIQUIDITY_EVIDENCE_CONFLICT",
        "LISTING_HISTORY_CONFLICT",
    }

    download = json.loads(snapshot_ui_download_json(state))
    assert download["snapshot_id"] == str(SNAPSHOT_ID)
    assert download["gateway_attempt_sha256"] == state.gateway_attempt_sha256
    assert download["gateway_preflight_formal_ready"] is True
    assert download["gateway_batches"][0]["endpoint"] == "qot_right_capture"
    assert download["gateway_identity_ledger"][0]["stock_id"] == "stock-BOUND"
    assert download["realtime_capability_probes"][0]["raw_request"] == {
        "code": "US.BOUND",
        "subtype": "QUOTE",
        "subscribe_push": False,
    }
    assert download["funnel_stages"][0]["stage_id"] == (
        "S0_DISCOVERED_US_CASH_SECURITIES"
    )
    assert download["candidate_count"] == 7
    assert download["members_sha256"] == state.members_sha256
    assert download["snapshot_content_sha256"] == state.snapshot_content_sha256
    assert download["snapshot_record_sha256"] == state.snapshot_record_sha256
    assert download["decisions"][0]["exchange_raw"] == "NASDAQ"
    assert download["decisions"][0]["raw_industry_references"]
    assert download["decisions"][0]["raw_industry_provider_version"] == (
        "10.10.7008"
    )
    assert download["decisions"][0]["raw_industry_source_version"] == "1009"
    assert download["decisions"][0]["raw_industry_schema_version"] == (
        "futu-screening/v2"
    )
    assert download["decisions"][0]["raw_plates"][0]["schema_version"] == (
        "futu-screening/v2"
    )


def test_snapshot_search_is_exact_case_insensitive_and_blank_safe(tmp_path) -> None:
    store, _ = _persist_complete_snapshot(tmp_path)
    state = load_snapshot_ui_state(store, SNAPSHOT_ID)

    assert find_security_decision(state, "  US.BOUND  ").symbol == "BOUND"  # type: ignore[union-attr]
    assert find_security_decision(state, "stock-bound").symbol == "BOUND"  # type: ignore[union-attr]
    assert find_security_decision(state, "") is None
    assert find_security_decision(state, "   ") is None
    assert find_security_decision(state, "BOUN") is None
    assert find_security_decision(state, "missing") is None


def test_load_snapshot_ui_state_projects_persisted_incomplete_preview(tmp_path) -> None:
    store, snapshot = _persist_incomplete_snapshot(tmp_path)

    state = load_snapshot_ui_state(store, snapshot.header.universe_snapshot_id)

    assert state.snapshot_kind == "PREVIEW"
    assert state.completeness == "INCOMPLETE"
    assert state.profile_version_id is None
    assert state.draft_id == "draft-task-12"
    assert state.gateway_attempt_status == "FAILED"
    assert state.gateway_attempt_reason_codes == ("UNIVERSE_INCOMPLETE_BLOCKER",)


def test_load_snapshot_ui_state_fails_closed_for_missing_corrupt_and_invalid_contract(
    tmp_path,
) -> None:
    store = UniverseSnapshotStore(tmp_path)
    with pytest.raises(SnapshotNotFoundError, match="snapshot not found"):
        load_snapshot_ui_state(store, SNAPSHOT_ID)

    persisted_store, _ = _persist_complete_snapshot(tmp_path / "corrupt")
    path = tmp_path / "corrupt" / f"{SNAPSHOT_ID}.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(SnapshotCorruptError, match="corrupt snapshot"):
        load_snapshot_ui_state(persisted_store, SNAPSHOT_ID)

    class InvalidStore:
        def get(self, snapshot_id):
            return {"is_member": False, "snapshot_id": str(snapshot_id)}

    with pytest.raises(SnapshotValidationError, match="UniverseSnapshot"):
        load_snapshot_ui_state(InvalidStore(), SNAPSHOT_ID)  # type: ignore[arg-type]
