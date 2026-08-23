"""Task 11 deterministic universe snapshot and immutable-store contracts."""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping, Sequence
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import Enum, IntEnum
from pathlib import Path
from uuid import UUID

import pytest

from tv_quant.pattern_finder.universe_foundation import (
    ActiveStatusMappingEntry,
    ApiBatchRecord,
    AttemptStatus,
    Completeness,
    Decision,
    EvidenceProvenance,
    EvidenceReference,
    FieldDecision,
    GatewayAttempt,
    GatewayPreflight,
    IdentityLedgerEntry,
    LiquidityEvidence,
    ListingHistoryEvidence,
    NormalizedPrerequisiteDecision,
    QualifiedActiveStatusMapping,
    QualifiedMarketStateConsistencyContract,
    QualifiedMarketStateRelationship,
    RawApiBatch,
    RawIndustryEvidence,
    SecurityEvaluation,
    SecurityEvaluationPrerequisites,
    SnapshotConflictError,
    SnapshotCorruptError,
    SnapshotKind,
    SnapshotNotFoundError,
    SnapshotStoreError,
    SnapshotValidationError,
    UniverseSecurityEvidence,
    UniverseSnapshot,
    UniverseSnapshotStore,
    build_funnel,
    build_snapshot,
    core_v1,
    members_sha256,
    prerequisites_sha256,
    snapshot_content_sha256,
    snapshot_record_sha256,
)
from tv_quant.pattern_finder.universe_foundation import snapshots as snapshots_module


NOW = datetime(2026, 8, 21, 21, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
SDK_VERSION = "10.10.7008"
OPEND_VERSION = "1009"
STAGES = (
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


class StringEnum(str, Enum):
    OK = "OK"


class NumericEnum(IntEnum):
    OK = 0


def _reference(locator: str, sha256: str = SHA_A) -> EvidenceReference:
    return EvidenceReference("FUTU", locator, sha256)


def _mapping(*, reference_sha256: str = SHA_A) -> QualifiedActiveStatusMapping:
    return QualifiedActiveStatusMapping(
        provider="FUTU",
        provider_sdk_version=SDK_VERSION,
        opend_server_version=OPEND_VERSION,
        mapping_version="active/v1",
        entries=(ActiveStatusMappingEntry("NORMAL", Decision.PASS, "ACTIVE_ALLOWED"),),
        qualified_at_utc=NOW,
        qualification_references=(
            EvidenceReference(
                "qualification",
                "futu://qualification/active/v1",
                reference_sha256,
            ),
        ),
    )


def _market_state_contract() -> QualifiedMarketStateConsistencyContract:
    return QualifiedMarketStateConsistencyContract(
        provider="FUTU",
        provider_sdk_version=SDK_VERSION,
        opend_server_version=OPEND_VERSION,
        mapping_version="market-state-consistency/after-hours-end-v1",
        qualified_at_utc=NOW,
        qualification_references=(
            EvidenceReference(
                "qualification",
                "futu://qualification/market-state/after-hours-end",
                SHA_A,
            ),
        ),
        qualified_relationships=(
            QualifiedMarketStateRelationship(
                "AFTER_HOURS_END", "XNYS_NON_SESSION"
            ),
        ),
    )


def _provenance(code: str, *, sha256: str = SHA_A) -> EvidenceProvenance:
    return EvidenceProvenance(
        provider="FUTU",
        provider_version=SDK_VERSION,
        source_version=OPEND_VERSION,
        schema_version="futu-screening/v2",
        observed_at_utc=NOW,
        references=(_reference(f"futu://screening/{code}", sha256),),
    )


def _evidence(
    symbol: str,
    *,
    stock_id: str | None = None,
    futu_code: str | None = None,
    sha256: str = SHA_A,
) -> UniverseSecurityEvidence:
    code = futu_code or f"US.{symbol}"
    provenance = _provenance(code, sha256=sha256)
    return UniverseSecurityEvidence(
        schema_version="universe-security-evidence/v1",
        stock_id=stock_id or f"stock-{symbol}",
        futu_code=code,
        symbol=symbol,
        name=f"{symbol} Inc.",
        exchange_raw="NASDAQ",
        security_type_raw="STOCK",
        delisting=False,
        suspension=False,
        security_status_raw="NORMAL",
        price_usd=Decimal("10.00"),
        market_cap_usd=Decimal("1000000000.00"),
        provenance=provenance,
        raw_industry=RawIndustryEvidence("Technology", provenance),
        raw_plates=(),
        classification_evidence=(),
        liquidity=LiquidityEvidence(
            metric_id="FUTU_AVG_TURNOVER_20D",
            evidence_version="futu-screening-liquidity/v1",
            avg_turnover_20d_usd=Decimal("20000000.00"),
            avg_volume_20d_shares=Decimal("2000000"),
            window_days=20,
            currency="USD",
            raw_value="20000000.00",
            provenance=provenance,
            reason_codes=(),
        ),
        listing_history=ListingHistoryEvidence(
            metric_id="FUTU_LISTED_DAYS",
            evidence_version="futu-screening-listing-history/v1",
            listed_days=300,
            listing_date=date(2020, 1, 2),
            raw_value="300",
            provenance=provenance,
            reason_codes=(),
        ),
        reason_codes=(),
    )


def _normalized(
    decision: Decision, reason_code: str, reference: EvidenceReference
) -> NormalizedPrerequisiteDecision:
    return NormalizedPrerequisiteDecision(decision, reason_code, (reference,))


def _prerequisite(
    evidence: UniverseSecurityEvidence,
    *,
    identity: tuple[Decision, str] = (Decision.PASS, "IDENTITY_VERIFIED"),
    active: tuple[Decision, str] = (Decision.PASS, "ACTIVE_ALLOWED"),
) -> SecurityEvaluationPrerequisites:
    reference = evidence.provenance.references[0]
    return SecurityEvaluationPrerequisites(
        stock_id=evidence.stock_id,
        futu_code=evidence.futu_code,
        active_status=_normalized(*active, reference),
        identity=_normalized(*identity, reference),
    )


def _evaluation(
    evidence: UniverseSecurityEvidence,
    prerequisite: SecurityEvaluationPrerequisites,
    *,
    change: tuple[str, Decision, str] | None = None,
) -> SecurityEvaluation:
    changes = {} if change is None else {change[0]: (change[1], change[2])}
    identity = prerequisite.identity
    active = prerequisite.active_status
    assert identity is not None and active is not None
    changes.setdefault("S1_IDENTITY_VALID", (identity.decision, identity.reason_code))
    changes.setdefault("S4_ACTIVE_STATUS_ALLOWED", (active.decision, active.reason_code))
    decisions = tuple(
        FieldDecision(
            field_id=stage,
            raw_value="upstream raw",
            normalized_value=(
                "NASDAQ"
                if stage == "S2_EXCHANGE_ALLOWED"
                else "COMMON_STOCK"
                if stage == "S3_SECURITY_CLASS_ALLOWED"
                else "upstream normalized"
            ),
            operator=None,
            threshold=None,
            decision=changes.get(stage, (Decision.PASS, f"{stage}_PASS"))[0],
            reason_code=changes.get(stage, (Decision.PASS, f"{stage}_PASS"))[1],
            evidence_source="TASK_6",
            evidence_observed_at_utc=NOW,
            evidence_version="task-6/v1",
            evidence_references=(
                identity.evidence_references
                if stage == "S1_IDENTITY_VALID"
                else active.evidence_references
                if stage == "S4_ACTIVE_STATUS_ALLOWED"
                else evidence.provenance.references
            ),
        )
        for stage in STAGES
    )
    first = next((item for item in decisions if item.decision is not Decision.PASS), None)
    return SecurityEvaluation(
        stock_id=evidence.stock_id,
        futu_code=evidence.futu_code,
        symbol=evidence.symbol,
        name=evidence.name,
        field_decisions=decisions,
        first_exit_stage=None if first is None else first.field_id,
        first_exit_reason_code=None if first is None else first.reason_code,
        is_member=first is None,
        is_quarantined=any(
            item.decision is Decision.UNKNOWN for item in decisions
        ),
    )


def _attempt(
    evidence: tuple[UniverseSecurityEvidence, ...],
    prerequisites: tuple[SecurityEvaluationPrerequisites, ...],
    *,
    mapping: QualifiedActiveStatusMapping | None = None,
    attempt_id: str = "attempt-11-fixture",
    status: AttemptStatus = AttemptStatus.SUCCEEDED,
    completeness: Completeness = Completeness.COMPLETE,
    formal_ready: bool = True,
    reason_codes: tuple[str, ...] = (),
    preflight_reason_codes: tuple[str, ...] | None = None,
    batches: tuple[ApiBatchRecord, ...] | None = None,
    identity_ledger: tuple[IdentityLedgerEntry, ...] = (),
    realtime_capability_probes: tuple[RawApiBatch, ...] = (),
) -> GatewayAttempt:
    selected_mapping = mapping or _mapping()
    return GatewayAttempt(
        attempt_id=attempt_id,
        as_of_session=date(2026, 8, 21),
        observed_at_utc=NOW,
        provider_update_time=NOW,
        runtime_evidence_window_seconds=0.0,
        market_data_delay_class="UNKNOWN",
        market_state_consistency_contract=_market_state_contract(),
        active_status_mapping=selected_mapping,
        prerequisites_sha256=prerequisites_sha256(prerequisites),
        preflight=GatewayPreflight(
            provider="FUTU",
            provider_sdk_version=SDK_VERSION,
            opend_server_version=OPEND_VERSION,
            as_of_session=date(2026, 8, 21),
            observed_at_utc=NOW,
            provider_update_time=NOW,
            market_data_delay_class="UNKNOWN",
            formal_ready=formal_ready,
            reason_codes=(
                reason_codes
                if preflight_reason_codes is None
                else preflight_reason_codes
            ),
        ),
        evidence=evidence,
        prerequisites=prerequisites,
        batches=batches or (
            ApiBatchRecord("qot_right_capture", 1, SHA_A, SHA_B, NOW),
        ),
        identity_ledger=identity_ledger,
        attempt_status=status,
        completeness=completeness,
        reason_codes=reason_codes,
        realtime_capability_probes=realtime_capability_probes,
    )


def _inputs(
    *,
    unknown: bool = False,
    mapping: QualifiedActiveStatusMapping | None = None,
    attempt_id: str = "attempt-11-fixture",
) -> tuple[
    tuple[SecurityEvaluation, ...], GatewayAttempt, object
]:
    evidence = _evidence("AAPL")
    active = (
        (Decision.UNKNOWN, "ACTIVE_STATUS_UNKNOWN")
        if unknown
        else (Decision.PASS, "ACTIVE_ALLOWED")
    )
    prerequisite = _prerequisite(evidence, active=active)
    evaluation = _evaluation(evidence, prerequisite)
    evaluations = (evaluation,)
    return (
        evaluations,
        _attempt(
            (evidence,),
            (prerequisite,),
            mapping=mapping,
            attempt_id=attempt_id,
        ),
        build_funnel(evaluations),
    )


def _snapshot(
    *,
    snapshot_id: UUID = UUID("11111111-1111-4111-8111-111111111111"),
    created_at_utc: datetime = NOW,
    unknown: bool = False,
    mapping: QualifiedActiveStatusMapping | None = None,
    attempt_id: str = "attempt-11-fixture",
) -> UniverseSnapshot:
    evaluations, attempt, funnel = _inputs(
        unknown=unknown, mapping=mapping, attempt_id=attempt_id
    )
    return build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=snapshot_id,
        created_at_utc=created_at_utc,
    )


def test_snapshot_is_frozen_utc_and_exports_three_distinct_hashes() -> None:
    snapshot = _snapshot()

    assert snapshot.header.snapshot_schema_version == "universe-snapshot/v1"
    assert len(snapshot.header.members_sha256) == 64
    assert len(snapshot.header.snapshot_sha256) == 64
    assert len(snapshot.header.snapshot_record_sha256) == 64
    assert snapshot.header.members_sha256 == members_sha256(snapshot.rows)
    assert snapshot.header.snapshot_sha256 == snapshot_content_sha256(snapshot)
    assert snapshot.header.snapshot_record_sha256 == snapshot_record_sha256(snapshot)
    with pytest.raises(FrozenInstanceError):
        snapshot.rows[0].is_member = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        snapshot.header.member_count = 0  # type: ignore[misc]
    with pytest.raises(SnapshotValidationError, match="UTC"):
        _snapshot(created_at_utc=NOW.replace(tzinfo=None))
    with pytest.raises(SnapshotValidationError, match="UUID"):
        _snapshot(snapshot_id=UUID(int=0))


def test_build_binds_profile_attempt_mapping_prerequisites_and_projected_rows() -> None:
    evaluations, attempt, funnel = _inputs()
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=UUID("22222222-2222-4222-8222-222222222222"),
        created_at_utc=NOW,
    )
    header, row = snapshot.header, snapshot.rows[0]

    assert header.profile_version_id == "CORE:v1"
    assert header.profile_content_sha256 == core_v1().content_sha256
    assert header.gateway_attempt_id == attempt.attempt_id
    assert header.active_status_mapping_provider == "FUTU"
    assert header.active_status_mapping_provider_sdk_version == SDK_VERSION
    assert header.active_status_mapping_opend_server_version == OPEND_VERSION
    assert (
        header.active_status_mapping_qualification_references
        == attempt.active_status_mapping.qualification_references
    )
    assert (
        header.active_status_mapping_sha256
        == attempt.active_status_mapping.active_status_mapping_sha256
    )
    assert header.prerequisites_sha256 == attempt.prerequisites_sha256
    assert row.identity_decision is Decision.PASS
    assert row.identity_reason_code == "IDENTITY_VERIFIED"
    assert row.active_status_decision is Decision.PASS
    assert row.active_status_reason_code == "ACTIVE_ALLOWED"
    assert row.raw_evidence_references == attempt.evidence[0].provenance.references
    assert row.is_member is evaluations[0].is_member


def test_input_order_is_canonical_and_duplicate_or_mismatched_keys_fail_closed() -> None:
    first_evidence, second_evidence = _evidence("MSFT"), _evidence("AAPL")
    first_prereq, second_prereq = _prerequisite(first_evidence), _prerequisite(second_evidence)
    first_eval = _evaluation(first_evidence, first_prereq)
    second_eval = _evaluation(second_evidence, second_prereq)
    attempt = _attempt((second_evidence, first_evidence), (first_prereq, second_prereq))
    forward = (first_eval, second_eval)
    reverse = tuple(reversed(forward))

    one = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=forward,
        funnel=build_funnel(forward),
        universe_snapshot_id=UUID("33333333-3333-4333-8333-333333333333"),
        created_at_utc=NOW,
    )
    two = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=reverse,
        funnel=build_funnel(reverse),
        universe_snapshot_id=one.header.universe_snapshot_id,
        created_at_utc=NOW,
    )
    assert one == two
    assert tuple((row.stock_id, row.futu_code) for row in one.rows) == tuple(
        sorted((row.stock_id, row.futu_code) for row in one.rows)
    )

    with pytest.raises(SnapshotValidationError, match="duplicate"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=attempt,
            evaluations=(first_eval, first_eval),
            funnel=build_funnel((first_eval,)),
            universe_snapshot_id=UUID("44444444-4444-4444-8444-444444444444"),
            created_at_utc=NOW,
        )

    mismatched_evidence = replace(first_evidence, futu_code="US.WRONG")
    mismatched_prereq = _prerequisite(mismatched_evidence)
    mismatched_eval = _evaluation(mismatched_evidence, mismatched_prereq)
    with pytest.raises(SnapshotValidationError, match="composite"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=attempt,
            evaluations=(mismatched_eval, second_eval),
            funnel=build_funnel((mismatched_eval, second_eval)),
            universe_snapshot_id=UUID("55555555-5555-4555-8555-555555555555"),
            created_at_utc=NOW,
        )


def test_same_stock_id_multiple_codes_conflict_rows_are_all_preserved() -> None:
    first_evidence = _evidence("AAA", stock_id="same", futu_code="US.AAA")
    second_evidence = _evidence("AAB", stock_id="same", futu_code="US.AAB")
    identity = (Decision.UNKNOWN, "UNIVERSE_IDENTITY_BLOCKER")
    first_prereq = _prerequisite(first_evidence, identity=identity)
    second_prereq = _prerequisite(second_evidence, identity=identity)
    evaluations = (
        _evaluation(first_evidence, first_prereq),
        _evaluation(second_evidence, second_prereq),
    )
    attempt = _attempt(
        (first_evidence, second_evidence), (first_prereq, second_prereq)
    )

    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=UUID("66666666-6666-4666-8666-666666666666"),
        created_at_utc=NOW,
    )

    assert tuple(row.futu_code for row in snapshot.rows) == ("US.AAA", "US.AAB")
    assert all(row.is_quarantined for row in snapshot.rows)
    assert snapshot.header.candidate_count == 2
    assert snapshot.header.quarantine_count == 2


def test_formal_and_preview_bindings_and_formal_attempt_gate() -> None:
    evaluations, attempt, funnel = _inputs()
    draft = replace(
        core_v1(),
        record_state=core_v1().record_state.DRAFT,
        published_at_utc=None,
        content_sha256=None,
        filter_content_sha256=None,
    )
    from tv_quant.pattern_finder.universe_foundation import UniverseDraft, draft_content_sha256

    draft_value = object.__new__(UniverseDraft)
    for field_id, value in {
        "draft_id": "draft-11",
        "profile_family_id": draft.profile_family_id,
        "profile_kind": draft.profile_kind,
        "display_name": draft.display_name,
        "parent_profile_version_id": draft.parent_profile_version_id,
        "created_at_utc": NOW,
        "change_note": "preview",
        "filters": draft.filters,
        "draft_content_sha256": "0" * 64,
    }.items():
        object.__setattr__(draft_value, field_id, value)
    object.__setattr__(
        draft_value, "draft_content_sha256", draft_content_sha256(draft_value)
    )
    draft_value.__post_init__()

    preview = build_snapshot(
        kind=SnapshotKind.PREVIEW,
        profile=None,
        draft=draft_value,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=UUID("77777777-7777-4777-8777-777777777777"),
        created_at_utc=NOW,
    )
    assert preview.header.profile_version_id is None
    assert preview.header.draft_id == "draft-11"

    for profile, supplied_draft in ((core_v1(), draft_value), (None, None)):
        with pytest.raises(SnapshotValidationError, match="profile|draft"):
            build_snapshot(
                kind=SnapshotKind.FORMAL,
                profile=profile,
                draft=supplied_draft,
                gateway_attempt=attempt,
                evaluations=evaluations,
                funnel=funnel,  # type: ignore[arg-type]
                universe_snapshot_id=UUID("88888888-8888-4888-8888-888888888888"),
                created_at_utc=NOW,
            )

    failed = replace(
        attempt,
        attempt_status=AttemptStatus.FAILED,
        completeness=Completeness.INCOMPLETE,
        preflight=replace(attempt.preflight, formal_ready=False),
    )
    with pytest.raises(SnapshotValidationError, match="FORMAL"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=failed,
            evaluations=evaluations,
            funnel=funnel,  # type: ignore[arg-type]
            universe_snapshot_id=UUID("99999999-9999-4999-8999-999999999999"),
            created_at_utc=NOW,
        )


def test_formal_rejects_partial_rows_and_prerequisite_projection_tamper() -> None:
    first_evidence, second_evidence = _evidence("AAPL"), _evidence("MSFT")
    first_prereq, second_prereq = _prerequisite(first_evidence), _prerequisite(second_evidence)
    first_eval, second_eval = _evaluation(first_evidence, first_prereq), _evaluation(second_evidence, second_prereq)
    attempt = _attempt((first_evidence, second_evidence), (first_prereq, second_prereq))

    with pytest.raises(SnapshotValidationError, match="partial|composite"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=attempt,
            evaluations=(first_eval,),
            funnel=build_funnel((first_eval,)),
            universe_snapshot_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
            created_at_utc=NOW,
        )

    tampered_decisions = list(first_eval.field_decisions)
    tampered_decisions[3] = replace(
        tampered_decisions[3], reason_code="FABRICATED_ACTIVE_REASON"
    )
    tampered = replace(first_eval, field_decisions=tuple(tampered_decisions))
    with pytest.raises(SnapshotValidationError, match="prerequisite|Active|active"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=_attempt((first_evidence,), (first_prereq,)),
            evaluations=(tampered,),
            funnel=build_funnel((tampered,)),
            universe_snapshot_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            created_at_utc=NOW,
        )


def test_three_hash_scopes_and_provenance_tamper_sensitivity() -> None:
    first = _snapshot()
    runtime_only = _snapshot(
        snapshot_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        created_at_utc=NOW.replace(microsecond=1),
        attempt_id="different-runtime-attempt-id",
    )
    changed_mapping = _snapshot(mapping=_mapping(reference_sha256=SHA_B))

    assert first.header.members_sha256 == runtime_only.header.members_sha256
    assert first.header.snapshot_sha256 == runtime_only.header.snapshot_sha256
    assert first.header.snapshot_record_sha256 != runtime_only.header.snapshot_record_sha256
    assert first.header.members_sha256 == changed_mapping.header.members_sha256
    assert first.header.snapshot_sha256 != changed_mapping.header.snapshot_sha256

    non_member_evaluations, attempt, _ = _inputs()
    failed_decisions = list(non_member_evaluations[0].field_decisions)
    failed_decisions[4] = replace(
        failed_decisions[4], decision=Decision.FAIL, reason_code="PRICE_BELOW_MINIMUM"
    )
    failed_eval = replace(
        non_member_evaluations[0],
        field_decisions=tuple(failed_decisions),
        first_exit_stage="S5_PRICE_ALLOWED",
        first_exit_reason_code="PRICE_BELOW_MINIMUM",
        is_member=False,
    )
    non_member = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=(failed_eval,),
        funnel=build_funnel((failed_eval,)),
        universe_snapshot_id=UUID("dddddddd-dddd-4ddd-8ddd-dddddddddddd"),
        created_at_utc=NOW,
    )
    assert first.header.members_sha256 != non_member.header.members_sha256

    with pytest.raises(SnapshotValidationError, match="members_sha256"):
        replace(
            first,
            header=replace(first.header, members_sha256=SHA_B),
        )


def test_unknown_quarantine_provenance_is_preserved_without_recalculation() -> None:
    evaluations, _, _ = _inputs(unknown=True)
    snapshot = _snapshot(unknown=True)
    row = snapshot.rows[0]

    assert row.active_status_decision is Decision.UNKNOWN
    assert row.active_status_reason_code == "ACTIVE_STATUS_UNKNOWN"
    assert row.active_status_evidence_references
    assert row.is_quarantined is True
    assert row.is_member is evaluations[0].is_member is False
    assert row.first_exit_stage == evaluations[0].first_exit_stage


def test_store_append_get_idempotence_conflict_missing_and_forbidden_methods(
    tmp_path: Path,
) -> None:
    store = UniverseSnapshotStore(root=tmp_path)
    snapshot = _snapshot()

    persisted = store.append(snapshot)
    path = tmp_path / f"{snapshot.header.universe_snapshot_id}.json"
    before = path.stat().st_mtime_ns
    assert persisted == snapshot
    assert store.get(snapshot.header.universe_snapshot_id) == snapshot
    assert store.append(snapshot) == snapshot
    assert path.stat().st_mtime_ns == before

    conflicting = _snapshot(created_at_utc=NOW.replace(microsecond=2))
    with pytest.raises(SnapshotConflictError):
        store.append(conflicting)
    with pytest.raises(SnapshotNotFoundError):
        store.get(UUID("eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"))

    assert set(vars(UniverseSnapshotStore)) & {
        "overwrite",
        "update",
        "delete",
        "latest",
        "list",
        "read",
    } == set()
    assert tuple(inspect.signature(UniverseSnapshotStore).parameters) == ("root",)


@pytest.mark.parametrize("payload", (b"{", b"{}", b'{"truncated":true}'))
def test_store_corruption_is_fail_closed(tmp_path: Path, payload: bytes) -> None:
    store = UniverseSnapshotStore(root=tmp_path)
    snapshot = _snapshot()
    store.append(snapshot)
    path = tmp_path / f"{snapshot.header.universe_snapshot_id}.json"
    path.write_bytes(payload)

    with pytest.raises(SnapshotCorruptError):
        store.get(snapshot.header.universe_snapshot_id)


def test_store_hash_mismatch_is_corruption(tmp_path: Path) -> None:
    store = UniverseSnapshotStore(root=tmp_path)
    snapshot = _snapshot()
    store.append(snapshot)
    path = tmp_path / f"{snapshot.header.universe_snapshot_id}.json"
    payload = path.read_text(encoding="utf-8").replace(
        snapshot.rows[0].symbol, "TAMPERED", 1
    )
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(SnapshotCorruptError):
        store.get(snapshot.header.universe_snapshot_id)


def test_store_failure_leaves_no_partial_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UniverseSnapshotStore(root=tmp_path)
    snapshot = _snapshot()

    def fail_atomic_create(*args: object, **kwargs: object) -> None:
        raise OSError("simulated storage failure")

    monkeypatch.setattr(snapshots_module, "_atomic_create", fail_atomic_create)
    with pytest.raises(SnapshotStoreError, match="simulated storage failure"):
        store.append(snapshot)
    assert not (tmp_path / f"{snapshot.header.universe_snapshot_id}.json").exists()


def test_snapshot_retains_complete_batch_and_identity_ledgers_in_content_hash(
    tmp_path: Path,
) -> None:
    evidence = _evidence("AAPL")
    prerequisite = _prerequisite(evidence)
    evaluation = _evaluation(evidence, prerequisite)
    evaluations = (evaluation,)
    batches = (
        ApiBatchRecord("qot_right_capture", 1, SHA_A, SHA_B, NOW),
        ApiBatchRecord("market_snapshots", 2, SHA_B, SHA_A, NOW),
    )
    ledger = (
        IdentityLedgerEntry(
            stock_id=evidence.stock_id,
            futu_code=evidence.futu_code,
            decision=Decision.PASS,
            reason_code="IDENTITY_RECONCILED",
            competing_stock_ids=(evidence.stock_id,),
            competing_futu_codes=(evidence.futu_code,),
            evidence_references=evidence.provenance.references,
            reconciliation_completed=True,
        ),
    )
    attempt = _attempt(
        (evidence,),
        (prerequisite,),
        batches=batches,
        identity_ledger=ledger,
    )
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=UUID("12121212-1212-4212-8212-121212121212"),
        created_at_utc=NOW,
    )

    assert snapshot.header.gateway_batches == batches
    assert snapshot.header.gateway_identity_ledger == ledger
    loaded = UniverseSnapshotStore(tmp_path).append(snapshot)
    assert loaded.header.gateway_batches == batches
    assert loaded.header.gateway_identity_ledger == ledger

    changed_attempt = replace(
        attempt,
        batches=(batches[0], replace(batches[1], response_hash="c" * 64)),
    )
    changed = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=changed_attempt,
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=UUID("13131313-1313-4313-8313-131313131313"),
        created_at_utc=NOW,
    )
    assert snapshot.header.snapshot_sha256 != changed.header.snapshot_sha256

    changed_attempt = replace(
        attempt,
        identity_ledger=(replace(ledger[0], reason_code="IDENTITY_RECONCILED_V2"),),
    )
    changed = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=changed_attempt,
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=UUID("14141414-1414-4414-8414-141414141414"),
        created_at_utc=NOW,
    )
    assert snapshot.header.snapshot_sha256 != changed.header.snapshot_sha256


def test_store_round_trip_preserves_nested_sequences_and_reserved_tag_mappings(
    tmp_path: Path,
) -> None:
    evaluations, attempt, funnel = _inputs()
    decisions = list(evaluations[0].field_decisions)
    decisions[4] = replace(
        decisions[4],
        raw_value=["outer-list", ["inner-list"]],
        normalized_value=("outer-tuple", ["nested-list"]),
        threshold={"__decimal__": "raw-mapping-value"},
    )
    evaluations = (replace(evaluations[0], field_decisions=tuple(decisions)),)
    funnel = build_funnel(evaluations)
    probe = RawApiBatch(
        endpoint="realtime_quote_capability_probe",
        batch_index=1,
        raw_request={
            "code": "US.AAPL",
            "subtype": "QUOTE",
            "subscribe_push": False,
            "nested": [1, [2, 3]],
        },
        raw_response={
            "reserved_decimal": {"__decimal__": "not-a-decimal"},
            "reserved_codec": {"__snapshot_type__": "tuple", "items": [1]},
            "rows": [{"values": ["a", "b"]}],
        },
        request_hash=SHA_A,
        response_hash=SHA_B,
        ret_code=0,
        acquisition_status="SUCCESS",
        acquired_at_utc=NOW,
    )
    attempt = replace(attempt, realtime_capability_probes=(probe,))
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=UUID("15151515-1515-4515-8515-151515151515"),
        created_at_utc=NOW,
    )

    loaded = UniverseSnapshotStore(tmp_path).append(snapshot)

    assert loaded == snapshot
    assert loaded.header.realtime_capability_probes[0].raw_request == probe.raw_request
    assert loaded.header.realtime_capability_probes[0].raw_response == probe.raw_response
    assert isinstance(
        loaded.header.realtime_capability_probes[0].raw_request["nested"], tuple
    )
    loaded_decision = loaded.rows[0].field_decisions[4]
    assert isinstance(loaded_decision.raw_value, Sequence)
    assert not isinstance(loaded_decision.raw_value, list)
    assert isinstance(loaded_decision.raw_value[1], Sequence)
    assert not isinstance(loaded_decision.raw_value[1], list)
    assert type(loaded_decision.normalized_value) is tuple
    assert isinstance(loaded_decision.normalized_value[1], Sequence)
    assert not isinstance(loaded_decision.normalized_value[1], list)
    assert loaded_decision.threshold == {"__decimal__": "raw-mapping-value"}


def test_formal_rejects_preflight_only_blockers() -> None:
    evaluations, attempt, funnel = _inputs()
    blocked = replace(
        attempt,
        preflight=replace(
            attempt.preflight,
            formal_ready=True,
            reason_codes=("UNIVERSE_FRESHNESS_BLOCKER",),
        ),
        reason_codes=(),
    )

    with pytest.raises(SnapshotValidationError, match="FORMAL"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=blocked,
            evaluations=evaluations,
            funnel=funnel,  # type: ignore[arg-type]
            universe_snapshot_id=UUID("16161616-1616-4616-8616-161616161616"),
            created_at_utc=NOW,
        )


def test_invalid_decimal_codec_is_typed_corruption(tmp_path: Path) -> None:
    store = UniverseSnapshotStore(tmp_path)
    snapshot = store.append(_snapshot())
    path = tmp_path / f"{snapshot.header.universe_snapshot_id}.json"
    payload = path.read_text(encoding="utf-8").replace(
        '"__decimal__":"10.00"', '"__decimal__":"not-a-decimal"', 1
    )
    assert "not-a-decimal" in payload
    path.write_text(payload, encoding="utf-8")

    with pytest.raises(SnapshotCorruptError):
        store.get(snapshot.header.universe_snapshot_id)


def test_get_is_pure_parse_and_does_not_call_task6_or_task8_derivation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tv_quant.pattern_finder.universe_foundation import funnel as funnel_module

    store = UniverseSnapshotStore(tmp_path)
    snapshot = store.append(_snapshot())

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("upstream derivation called during get")

    monkeypatch.setattr(funnel_module, "build_funnel", forbidden)
    monkeypatch.setattr(SecurityEvaluation, "__post_init__", forbidden)

    assert store.get(snapshot.header.universe_snapshot_id) == snapshot


@pytest.mark.parametrize(
    ("field_id", "replacement"),
    (
        ("as_of_session", date(2026, 8, 20)),
        ("observed_at_utc", NOW + timedelta(seconds=1)),
        ("provider_update_time", NOW + timedelta(seconds=1)),
        ("market_data_delay_class", "DELAYED"),
        ("provider", "OTHER"),
        ("provider_sdk_version", "other-sdk"),
        ("opend_server_version", "other-opend"),
    ),
)
def test_formal_rejects_preflight_provenance_mismatch(
    field_id: str, replacement: object
) -> None:
    evaluations, attempt, funnel = _inputs()
    mismatched = replace(
        attempt,
        preflight=replace(attempt.preflight, **{field_id: replacement}),
    )

    with pytest.raises(SnapshotValidationError, match="preflight"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=mismatched,
            evaluations=evaluations,
            funnel=funnel,  # type: ignore[arg-type]
            universe_snapshot_id=UUID("17171717-1717-4717-8717-171717171717"),
            created_at_utc=NOW,
        )


def test_preflight_provenance_is_persisted_and_content_sensitive() -> None:
    evaluations, attempt, funnel = _inputs()
    first = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=UUID("18181818-1818-4818-8818-181818181818"),
        created_at_utc=NOW,
    )
    changed_time = NOW + timedelta(seconds=1)
    changed_attempt = replace(
        attempt,
        observed_at_utc=changed_time,
        preflight=replace(attempt.preflight, observed_at_utc=changed_time),
    )
    second = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=changed_attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=UUID("19191919-1919-4919-8919-191919191919"),
        created_at_utc=NOW,
    )

    assert first.header.gateway_preflight_as_of_session == attempt.preflight.as_of_session
    assert (
        first.header.gateway_preflight_observed_at_utc
        == attempt.preflight.observed_at_utc
    )
    assert (
        first.header.gateway_preflight_provider_update_time
        == attempt.preflight.provider_update_time
    )
    assert (
        first.header.gateway_preflight_market_data_delay_class
        == attempt.preflight.market_data_delay_class
    )
    assert first.header.snapshot_sha256 != second.header.snapshot_sha256


def test_audit_codec_round_trips_whitelisted_enum_and_dataclass(
    tmp_path: Path,
) -> None:
    evaluations, attempt, _ = _inputs()
    reference = _reference("futu://nested/audit")
    nested = {
        "enum": Decision.UNKNOWN,
        "dataclass": reference,
        "list": [Decision.FAIL, {"reference": reference}],
    }
    decisions = list(evaluations[0].field_decisions)
    decisions[4] = replace(
        decisions[4],
        raw_value=nested,
        normalized_value=(Decision.PASS, reference),
        threshold={"decision": Decision.FAIL, "reference": reference},
    )
    evaluations = (replace(evaluations[0], field_decisions=tuple(decisions)),)
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=UUID("20202020-2020-4020-8020-202020202020"),
        created_at_utc=NOW,
    )

    loaded = UniverseSnapshotStore(tmp_path).append(snapshot)
    raw_value = loaded.rows[0].field_decisions[4].raw_value
    assert isinstance(raw_value, Mapping)
    assert raw_value["enum"] is Decision.UNKNOWN
    assert raw_value["dataclass"] == reference
    assert raw_value["list"][0] is Decision.FAIL
    assert raw_value["list"][1]["reference"] == reference
    assert loaded == snapshot


def test_snapshot_defensively_freezes_nested_audit_values() -> None:
    evaluations, attempt, _ = _inputs()
    caller_owned = {"items": [{"values": [1, 2]}]}
    decisions = list(evaluations[0].field_decisions)
    decisions[4] = replace(decisions[4], raw_value=caller_owned)
    evaluations = (replace(evaluations[0], field_decisions=tuple(decisions)),)
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=UUID("21212121-2121-4121-8121-212121212121"),
        created_at_utc=NOW,
    )
    before = snapshot.header.snapshot_sha256
    frozen = snapshot.rows[0].field_decisions[4].raw_value

    caller_owned["items"][0]["values"].append(3)
    assert snapshot.header.snapshot_sha256 == before
    assert tuple(frozen["items"][0]["values"]) == (1, 2)
    with pytest.raises((AttributeError, TypeError)):
        frozen["items"][0]["values"].append(4)
    with pytest.raises(TypeError):
        frozen["new"] = "mutation"  # type: ignore[index]


def test_unsupported_audit_dataclass_is_rejected_before_persistence(
    tmp_path: Path,
) -> None:
    @dataclass(frozen=True)
    class UnsupportedAuditValue:
        value: str

    evaluations, attempt, _ = _inputs()
    decisions = list(evaluations[0].field_decisions)
    decisions[4] = replace(
        decisions[4], raw_value=UnsupportedAuditValue("unsafe-type")
    )
    evaluations = (replace(evaluations[0], field_decisions=tuple(decisions)),)

    with pytest.raises(SnapshotValidationError, match="unsupported audit"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=attempt,
            evaluations=evaluations,
            funnel=build_funnel(evaluations),
            universe_snapshot_id=UUID("22222222-2222-4222-8222-222222222223"),
            created_at_utc=NOW,
        )
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "corruption",
    ("malformed", "truncated", "noncanonical", "hash_mismatch"),
)
def test_append_propagates_existing_corruption_instead_of_conflict(
    tmp_path: Path, corruption: str
) -> None:
    store = UniverseSnapshotStore(tmp_path)
    snapshot = store.append(_snapshot())
    path = tmp_path / f"{snapshot.header.universe_snapshot_id}.json"
    original = path.read_bytes()
    if corruption == "malformed":
        payload = b"{"
    elif corruption == "truncated":
        payload = original[:-7]
    elif corruption == "noncanonical":
        payload = json.dumps(json.loads(original), indent=2).encode("utf-8")
    else:
        payload = original.replace(b'"symbol":"AAPL"', b'"symbol":"EVIL"', 1)
    path.write_bytes(payload)

    with pytest.raises(SnapshotCorruptError):
        store.append(snapshot)


def test_append_validates_round_trip_before_final_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = UniverseSnapshotStore(tmp_path)
    snapshot = _snapshot()

    def fail_round_trip(*args: object, **kwargs: object) -> None:
        raise SnapshotValidationError("simulated unreadable record")

    monkeypatch.setattr(snapshots_module, "_snapshot_from_payload", fail_round_trip)
    with pytest.raises(SnapshotValidationError, match="unreadable"):
        store.append(snapshot)
    assert not (tmp_path / f"{snapshot.header.universe_snapshot_id}.json").exists()


@pytest.mark.parametrize("corruption", ("duplicate", "missing", "swapped"))
def test_store_rejects_invalid_fixed_funnel_stage_schema(
    tmp_path: Path, corruption: str
) -> None:
    store = UniverseSnapshotStore(tmp_path)
    snapshot = store.append(_snapshot())
    path = tmp_path / f"{snapshot.header.universe_snapshot_id}.json"
    payload = json.loads(path.read_bytes())
    stage_items = payload["funnel"]["stages"]["items"]
    if corruption == "duplicate":
        stage_items[1]["stage_id"] = stage_items[0]["stage_id"]
    elif corruption == "missing":
        stage_items.pop(5)
    else:
        stage_items[1], stage_items[2] = stage_items[2], stage_items[1]
    with pytest.raises(SnapshotValidationError, match="fixed S0-S10"):
        snapshots_module._funnel_from_payload(payload["funnel"])
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(SnapshotCorruptError):
        store.get(snapshot.header.universe_snapshot_id)


@pytest.mark.parametrize("ret_code", (StringEnum.OK, NumericEnum.OK))
def test_unsupported_probe_enum_fails_closed_before_persistence(
    tmp_path: Path, ret_code: object
) -> None:
    evaluations, attempt, funnel = _inputs()
    probe = RawApiBatch(
        endpoint="realtime_quote_capability_probe",
        batch_index=1,
        raw_request={
            "code": "US.AAPL",
            "subtype": "QUOTE",
            "subscribe_push": False,
        },
        raw_response={"rows": []},
        request_hash=SHA_A,
        response_hash=SHA_B,
        ret_code=ret_code,
        acquisition_status="SUCCESS",
        acquired_at_utc=NOW,
    )
    attempt = replace(attempt, realtime_capability_probes=(probe,))

    with pytest.raises(SnapshotValidationError, match="unsupported audit type"):
        build_snapshot(
            kind=SnapshotKind.FORMAL,
            profile=core_v1(),
            draft=None,
            gateway_attempt=attempt,
            evaluations=evaluations,
            funnel=funnel,  # type: ignore[arg-type]
            universe_snapshot_id=UUID("24242424-2424-4424-8424-242424242424"),
            created_at_utc=NOW,
        )
    assert list(tmp_path.iterdir()) == []


def test_whitelisted_probe_enum_round_trip_preserves_exact_type(tmp_path: Path) -> None:
    evaluations, attempt, funnel = _inputs()
    probe = RawApiBatch(
        endpoint="realtime_quote_capability_probe",
        batch_index=1,
        raw_request={
            "code": "US.AAPL",
            "subtype": "QUOTE",
            "subscribe_push": False,
        },
        raw_response={"rows": []},
        request_hash=SHA_A,
        response_hash=SHA_B,
        ret_code=Decision.UNKNOWN,
        acquisition_status="SUCCESS",
        acquired_at_utc=NOW,
    )
    attempt = replace(attempt, realtime_capability_probes=(probe,))
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=UUID("25252525-2525-4525-8525-252525252525"),
        created_at_utc=NOW,
    )

    loaded = UniverseSnapshotStore(tmp_path).append(snapshot)
    restored = loaded.header.realtime_capability_probes[0].ret_code
    assert type(restored) is Decision
    assert restored is Decision.UNKNOWN


@pytest.mark.parametrize(
    "encoded",
    (
        {
            "__snapshot_codec_type__": "audit-enum",
            "name": "UnknownEnum",
            "value": "OK",
        },
        {
            "__snapshot_codec_type__": "audit-enum",
            "name": "Decision",
            "value": "NOT_A_DECISION",
        },
        {
            "__snapshot_codec_type__": "audit-enum",
            "name": "Decision",
            "value": "PASS",
            "module": "untrusted.module",
        },
        {
            "__snapshot_codec_type__": "enum",
            "module": "untrusted.module",
            "qualname": "SomeEnum",
            "name": "OK",
            "value": "OK",
        },
    ),
)
def test_unknown_or_mismatched_enum_codec_tag_fails_closed(
    encoded: dict[str, object]
) -> None:
    with pytest.raises((SnapshotValidationError, ValueError)):
        snapshots_module._decode_audit(encoded)


def test_persisted_unknown_enum_tag_is_typed_corruption(tmp_path: Path) -> None:
    evaluations, attempt, funnel = _inputs()
    probe = RawApiBatch(
        endpoint="realtime_quote_capability_probe",
        batch_index=1,
        raw_request={
            "code": "US.AAPL",
            "subtype": "QUOTE",
            "subscribe_push": False,
        },
        raw_response={"rows": []},
        request_hash=SHA_A,
        response_hash=SHA_B,
        ret_code=Decision.UNKNOWN,
        acquisition_status="SUCCESS",
        acquired_at_utc=NOW,
    )
    attempt = replace(attempt, realtime_capability_probes=(probe,))
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=UUID("27272727-2727-4727-8727-272727272727"),
        created_at_utc=NOW,
    )
    store = UniverseSnapshotStore(tmp_path)
    store.append(snapshot)
    path = tmp_path / f"{snapshot.header.universe_snapshot_id}.json"
    payload = json.loads(path.read_bytes())
    payload["header"]["realtime_capability_probes"]["items"][0]["ret_code"] = {
        "__snapshot_codec_type__": "audit-enum",
        "name": "UnknownEnum",
        "value": "OK",
    }
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(SnapshotCorruptError):
        store.get(snapshot.header.universe_snapshot_id)


def test_snapshot_takes_deep_ownership_of_all_generic_audit_values(
    tmp_path: Path,
) -> None:
    evaluations, attempt, _ = _inputs()
    ret_code_payload = {
        "a": [{"b": [1, 2]}],
        "nested": {"value": "original"},
    }
    observed_payload = {
        "observed": [{"values": ["original"]}],
    }
    probe = RawApiBatch(
        endpoint="realtime_quote_capability_probe",
        batch_index=1,
        raw_request={
            "code": "US.AAPL",
            "subtype": "QUOTE",
            "subscribe_push": False,
            "nested": [{"request": [1, 2]}],
        },
        raw_response={"rows": [{"response": [3, 4]}]},
        request_hash=SHA_A,
        response_hash=SHA_B,
        ret_code=ret_code_payload,
        acquisition_status="SUCCESS",
        acquired_at_utc=NOW,
    )
    attempt = replace(attempt, realtime_capability_probes=(probe,))
    decisions = list(evaluations[0].field_decisions)
    decisions[4] = replace(
        decisions[4], evidence_observed_at_utc=observed_payload
    )
    evaluations = (replace(evaluations[0], field_decisions=tuple(decisions)),)
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=build_funnel(evaluations),
        universe_snapshot_id=UUID("26262626-2626-4626-8626-262626262626"),
        created_at_utc=NOW,
    )
    before_hashes = (
        members_sha256(snapshot.rows),
        snapshot_content_sha256(snapshot),
        snapshot_record_sha256(snapshot),
    )

    ret_code_payload["a"][0]["b"].append(3)
    ret_code_payload["nested"]["value"] = "changed"
    observed_payload["observed"][0]["values"].append("changed")

    assert (
        members_sha256(snapshot.rows),
        snapshot_content_sha256(snapshot),
        snapshot_record_sha256(snapshot),
    ) == before_hashes
    frozen_ret_code = snapshot.header.realtime_capability_probes[0].ret_code
    frozen_observed = snapshot.rows[0].field_decisions[4].evidence_observed_at_utc
    assert tuple(frozen_ret_code["a"][0]["b"]) == (1, 2)
    assert frozen_ret_code["nested"]["value"] == "original"
    assert tuple(frozen_observed["observed"][0]["values"]) == ("original",)
    with pytest.raises(TypeError):
        frozen_ret_code["nested"]["value"] = "mutation"  # type: ignore[index]
    with pytest.raises(AttributeError):
        frozen_ret_code["a"][0]["b"].append(4)

    loaded = UniverseSnapshotStore(tmp_path).append(snapshot)
    assert snapshot_record_sha256(loaded) == snapshot_record_sha256(snapshot)
    assert loaded == snapshot
    loaded_ret_code = loaded.header.realtime_capability_probes[0].ret_code
    loaded_observed = loaded.rows[0].field_decisions[4].evidence_observed_at_utc
    with pytest.raises(TypeError):
        loaded_ret_code["nested"]["value"] = "mutation"  # type: ignore[index]
    with pytest.raises(AttributeError):
        loaded_observed["observed"][0]["values"].append("mutation")


def test_existing_frozen_audit_list_is_defensively_rebuilt(tmp_path: Path) -> None:
    evaluations, attempt, funnel = _inputs()
    caller_nested = {"values": [1, 2]}
    caller_frozen = snapshots_module._FrozenAuditList((caller_nested,))
    probe = RawApiBatch(
        endpoint="realtime_quote_capability_probe",
        batch_index=1,
        raw_request={
            "code": "US.AAPL",
            "subtype": "QUOTE",
            "subscribe_push": False,
        },
        raw_response={"rows": []},
        request_hash=SHA_A,
        response_hash=SHA_B,
        ret_code=caller_frozen,
        acquisition_status="SUCCESS",
        acquired_at_utc=NOW,
    )
    attempt = replace(attempt, realtime_capability_probes=(probe,))
    snapshot = build_snapshot(
        kind=SnapshotKind.FORMAL,
        profile=core_v1(),
        draft=None,
        gateway_attempt=attempt,
        evaluations=evaluations,
        funnel=funnel,  # type: ignore[arg-type]
        universe_snapshot_id=UUID("28282828-2828-4828-8828-282828282828"),
        created_at_utc=NOW,
    )
    owned = snapshot.header.realtime_capability_probes[0].ret_code
    before_hashes = (
        members_sha256(snapshot.rows),
        snapshot_content_sha256(snapshot),
        snapshot_record_sha256(snapshot),
    )

    assert owned is not caller_frozen
    assert owned[0] is not caller_nested
    caller_nested["values"].append(3)
    assert tuple(owned[0]["values"]) == (1, 2)
    assert (
        members_sha256(snapshot.rows),
        snapshot_content_sha256(snapshot),
        snapshot_record_sha256(snapshot),
    ) == before_hashes
    assert UniverseSnapshotStore(tmp_path).append(snapshot) == snapshot


@pytest.mark.parametrize(
    "fields_payload",
    (
        {
            "source_id": "FUTU",
            "source_locator": "futu://reference",
            "source_record_sha256": SHA_A,
            "module": "untrusted.module",
        },
        {
            "source_id": 123,
            "source_locator": "futu://reference",
            "source_record_sha256": SHA_A,
        },
        {
            "source_id": "FUTU",
            "source_locator": "futu://reference",
        },
    ),
)
def test_evidence_reference_codec_requires_exact_typed_field_schema(
    fields_payload: dict[str, object]
) -> None:
    encoded = {
        "__snapshot_codec_type__": "audit-dataclass",
        "name": "EvidenceReference",
        "fields": fields_payload,
    }
    with pytest.raises((SnapshotValidationError, ValueError)):
        snapshots_module._decode_audit(encoded)
