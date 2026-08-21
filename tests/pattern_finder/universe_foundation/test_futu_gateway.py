from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from tv_quant.pattern_finder.universe_foundation import (
    ActiveStatusMappingEntry,
    Decision,
    EvidenceReference,
    FutuUniverseGateway,
    IdentityLedgerEntry,
    QualifiedActiveStatusMapping,
    prerequisites_sha256,
)
from tv_quant.pattern_finder.universe_foundation.futu_adapter import RawApiBatch, RawApiPage
from tv_quant.pattern_finder.universe_foundation.evidence import SecurityClassificationEvidence


SHA = "a" * 64
NOW = datetime(2026, 8, 21, 21, tzinfo=UTC)


def _mapping() -> QualifiedActiveStatusMapping:
    return QualifiedActiveStatusMapping(
        provider="FUTU",
        provider_version="fake-sdk/1",
        mapping_version="active/v1",
        entries=(ActiveStatusMappingEntry("NORMAL", Decision.PASS, "ACTIVE_ALLOWED"),),
        qualified_at_utc=NOW,
        qualification_references=(EvidenceReference("qualification", "futu://tiny-sample", SHA),),
    )


def test_mapping_is_immutable_version_bound_and_tamper_sensitive() -> None:
    mapping = _mapping()

    assert mapping.entries[0].raw_value == "NORMAL"
    assert len(mapping.active_status_mapping_sha256) == 64
    with pytest.raises(ValueError, match="unique"):
        QualifiedActiveStatusMapping(
            provider="FUTU", provider_version="fake-sdk/1", mapping_version="active/v1",
            entries=(
                ActiveStatusMappingEntry("NORMAL", Decision.PASS, "ACTIVE_ALLOWED"),
                ActiveStatusMappingEntry("NORMAL", Decision.FAIL, "BLOCKED"),
            ),
            qualified_at_utc=NOW,
            qualification_references=(EvidenceReference("qualification", "futu://tiny-sample", SHA),),
        )
    with pytest.raises(ValueError, match="tamper"):
        replace(mapping, entries=(ActiveStatusMappingEntry("HALTED", Decision.FAIL, "HALTED"),))
    with pytest.raises(ValueError, match="concrete"):
        replace(mapping, provider_version="unknown", active_status_mapping_sha256="")


@pytest.mark.parametrize(
    ("delisting", "suspension", "expected"),
    ((True, True, "DELISTED"), (False, True, "SUSPENDED_AS_OF_SNAPSHOT"), (None, False, "ACTIVE_STATUS_UNKNOWN")),
)
def test_active_guard_order_is_fail_closed(
    delisting: object, suspension: object, expected: str
) -> None:
    gateway = FutuUniverseGateway(sdk=object(), clock=lambda: NOW, sleep=lambda _: None)
    decision = gateway.normalized_active_status(
        delisting=delisting,
        suspension=suspension,
        raw_status="NORMAL",
        evidence_references=(EvidenceReference("snapshot", "futu://snapshot/US.AAA", SHA),),
        mapping=_mapping(),
        provider="FUTU",
        provider_version="fake-sdk/1",
    )
    assert decision.reason_code == expected


def test_unknown_status_never_defaults_to_pass() -> None:
    gateway = FutuUniverseGateway(sdk=object(), clock=lambda: NOW, sleep=lambda _: None)
    decision = gateway.normalized_active_status(
        delisting=False, suspension=False, raw_status="NEW_ENUM", evidence_references=(),
        mapping=_mapping(), provider="FUTU", provider_version="fake-sdk/1",
    )
    assert decision.decision is Decision.UNKNOWN
    assert decision.reason_code == "ACTIVE_STATUS_UNKNOWN"


def test_active_mapping_requires_exact_provider_version_and_preserves_mapped_fail() -> None:
    gateway = FutuUniverseGateway(sdk=object(), clock=lambda: NOW, sleep=lambda _: None)
    refs = (EvidenceReference("snapshot", "futu://snapshot/US.AAA", SHA),)
    mismatch = gateway.normalized_active_status(delisting=False, suspension=False, raw_status="NORMAL", evidence_references=refs, mapping=_mapping(), provider="FUTU", provider_version="other-sdk/1")
    blocked_mapping = replace(_mapping(), entries=(ActiveStatusMappingEntry("NORMAL", Decision.FAIL, "STATUS_BLOCKED"),), active_status_mapping_sha256="")
    blocked = gateway.normalized_active_status(delisting=False, suspension=False, raw_status="NORMAL", evidence_references=refs, mapping=blocked_mapping, provider="FUTU", provider_version="fake-sdk/1")

    assert mismatch.decision is Decision.UNKNOWN
    assert blocked.decision is Decision.FAIL
    assert blocked.reason_code == "STATUS_BLOCKED"


@pytest.mark.parametrize("delisting,suspension,status", ((False, None, "NORMAL"), ("false", False, "NORMAL"), (False, 0, "NORMAL"), (False, False, None), (False, False, "")))
def test_active_unparseable_flags_or_status_are_unknown(delisting: object, suspension: object, status: object) -> None:
    gateway = FutuUniverseGateway(sdk=object(), clock=lambda: NOW, sleep=lambda _: None)
    decision = gateway.normalized_active_status(delisting=delisting, suspension=suspension, raw_status=status, evidence_references=(), mapping=_mapping(), provider="FUTU", provider_version="fake-sdk/1")

    assert decision.decision is Decision.UNKNOWN
    assert decision.reason_code == "ACTIVE_STATUS_UNKNOWN"


def test_collect_entrypoint_requires_utc_and_mapping_contract() -> None:
    gateway = FutuUniverseGateway(sdk=object(), clock=lambda: NOW, sleep=lambda _: None)
    with pytest.raises(ValueError, match="UTC"):
        gateway.collect(
            as_of_session=date(2026, 8, 20),
            observed_at_utc=datetime(2026, 8, 21),
            classification_provider=object(),
            active_status_mapping=_mapping(),
        )


class _Sdk:
    __version__ = "fake-sdk/1"


class _Adapter:
    def __init__(self, discovery_rows: list[dict[str, object]]) -> None:
        self.discovery_rows = discovery_rows

    @staticmethod
    def _batch(endpoint: str, rows: list[dict[str, object]]) -> RawApiBatch:
        return RawApiBatch(endpoint, 1, {}, {"rows": rows}, SHA, "b" * 64, 0, "SUCCESS", NOW)

    def discover_cash_securities(self):
        return (self._batch("discover_cash_securities", self.discovery_rows),)

    def screen_all_pages(self):
        rows = [
            {"code": row["code"], "name": "Example", "industry": "Technology", "price": "10.00", "market_cap": "1000000000.00", "avg_turnover": "20000000.00", "listed_days": 300}
            for row in self.discovery_rows
        ]
        return (RawApiPage("screen_all_pages", 1, {"page_from": 0}, True, {}, {"rows": rows}, SHA, "c" * 64, 0, "SUCCESS", NOW),)

    def market_snapshots(self, codes):
        rows = [
            {"code": code, "suspension": False, "sec_status": "NORMAL", "provider_update_time": "2026-08-21T20:00:00+00:00", "market_data_delay_class": "REALTIME", "regular_session_complete": True, "market_session": "XNYS_REGULAR"}
            for code in codes
        ]
        return (self._batch("market_snapshots", rows),)

    def owner_plates(self, codes):
        return (self._batch("owner_plates", []),)


class _ClassificationProvider:
    def classification_evidence(self, stock_id: str, futu_code: str, as_of_utc: datetime):
        return (
            SecurityClassificationEvidence(
                normalized_class="COMMON_STOCK", provider="APPROVED_SECURITY_MASTER",
                provider_value="Common", observed_at_utc=as_of_utc, source_version="master/v1",
                source_record_sha256="b" * 64, confidence="AUTHORITATIVE", notes="typed",
                reference=EvidenceReference("master", f"master://{stock_id}", "b" * 64), verified_by=None,
            ),
        )


def _collect(rows: list[dict[str, object]]):
    gateway = FutuUniverseGateway(sdk=_Sdk(), clock=lambda: NOW, sleep=lambda _: None)
    gateway._adapter = lambda: _Adapter(rows)  # type: ignore[method-assign]
    return gateway.collect(
        as_of_session=date(2026, 8, 21), observed_at_utc=NOW,
        classification_provider=_ClassificationProvider(), active_status_mapping=_mapping(),
    )


def test_collect_binds_one_prerequisite_per_evidence_key_and_is_deterministic() -> None:
    rows = [
        {"stock_id": "2", "code": "US.BBB", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
        {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
    ]
    first, second = _collect(rows), _collect(list(reversed(rows)))

    assert first.attempt_status.value == "SUCCEEDED"
    assert {(item.stock_id, item.futu_code) for item in first.evidence} == {(item.stock_id, item.futu_code) for item in first.prerequisites}
    assert first.prerequisites_sha256 == second.prerequisites_sha256


def test_same_stock_id_multiple_codes_keeps_rows_but_quarantines_identity() -> None:
    attempt = _collect([
        {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
        {"stock_id": "1", "code": "US.AAB", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
    ])

    assert attempt.attempt_status.value == "SUCCEEDED"
    assert [item.identity.decision for item in attempt.prerequisites] == [Decision.UNKNOWN, Decision.UNKNOWN]
    assert len(attempt.evidence) == 2


def test_same_code_multiple_stock_ids_fails_the_entire_attempt() -> None:
    attempt = _collect([
        {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
        {"stock_id": "2", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
    ])

    assert attempt.attempt_status.value == "FAILED"
    assert attempt.completeness.value == "INCOMPLETE"
    assert "UNIVERSE_IDENTITY_BLOCKER" in attempt.reason_codes
    assert attempt.prerequisites == ()


def test_duplicate_discovery_composite_key_fails_atomically_before_downstream_join() -> None:
    row = {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"}
    attempt = _collect([row, dict(row)])

    assert attempt.attempt_status.value == "FAILED"
    assert attempt.completeness.value == "INCOMPLETE"
    assert "FUTU_SCHEMA_BLOCKER" in attempt.reason_codes
    assert attempt.evidence == ()
    assert attempt.prerequisites == ()


def test_identity_pass_requires_explicit_completion_and_complete_attempt_requires_key_equality() -> None:
    ref = EvidenceReference("identity", "futu://identity/US.AAA", SHA)
    with pytest.raises(ValueError, match="completion"):
        IdentityLedgerEntry("1", "US.AAA", Decision.PASS, "IDENTITY_RECONCILED", ("1",), ("US.AAA",), (ref,))

    attempt = _collect([{"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"}])
    assert attempt.identity_ledger[0].reconciliation_completed is True
    with pytest.raises(ValueError, match="composite keys"):
        replace(attempt, prerequisites=(), prerequisites_sha256=prerequisites_sha256(()))


def test_missing_subtype_authority_is_retained_as_a_per_security_blocker() -> None:
    class EmptyClassificationProvider:
        def classification_evidence(self, stock_id: str, futu_code: str, as_of_utc: datetime):
            return ()

    gateway = FutuUniverseGateway(sdk=_Sdk(), clock=lambda: NOW, sleep=lambda _: None)
    gateway._adapter = lambda: _Adapter([{"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"}])  # type: ignore[method-assign]
    attempt = gateway.collect(as_of_session=date(2026, 8, 21), observed_at_utc=NOW, classification_provider=EmptyClassificationProvider(), active_status_mapping=_mapping())

    assert attempt.attempt_status.value == "SUCCEEDED"
    assert attempt.evidence[0].reason_codes == ("CLASSIFICATION_EVIDENCE_BLOCKER",)


def test_preflight_requires_calendar_close_and_explicit_completed_regular_session() -> None:
    gateway = FutuUniverseGateway(sdk=_Sdk(), clock=lambda: NOW, sleep=lambda _: None)
    preflight = gateway._preflight(as_of_session=date(2026, 8, 21), observed_at_utc=NOW, provider_version="fake-sdk/1", snapshots=({"provider_update_time": "2026-08-21T19:59:00+00:00", "market_data_delay_class": "REALTIME", "regular_session_complete": False, "market_session": "XNYS_REGULAR"},))

    assert preflight.formal_ready is False
    assert preflight.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


@pytest.mark.parametrize("completion", (None, 1, 1.0, "true", False))
def test_preflight_requires_a_real_boolean_completed_session_flag(completion: object) -> None:
    gateway = FutuUniverseGateway(sdk=_Sdk(), clock=lambda: NOW, sleep=lambda _: None)
    preflight = gateway._preflight(as_of_session=date(2026, 8, 21), observed_at_utc=NOW, provider_version="fake-sdk/1", snapshots=({"provider_update_time": "2026-08-21T20:00:00+00:00", "market_data_delay_class": "REALTIME", "regular_session_complete": completion, "market_session": "XNYS_REGULAR"},))

    assert preflight.formal_ready is False


@pytest.mark.parametrize(
    "as_of,update,delay,session",
    ((date(2026, 8, 20), "2026-08-21T20:00:00+00:00", "REALTIME", "XNYS_REGULAR"), (date(2026, 8, 21), "2026-08-21T20:00:00+00:00", "DELAYED", "XNYS_REGULAR"), (date(2026, 7, 3), "2026-07-03T20:00:00+00:00", "REALTIME", "XNYS_REGULAR"), (date(2026, 8, 21), "2026-08-21T20:00:00+00:00", "REALTIME", "PREVIEW")),
)
def test_preflight_rejects_session_timestamp_delay_and_intraday_inconsistency(as_of: date, update: str, delay: str, session: str) -> None:
    gateway = FutuUniverseGateway(sdk=_Sdk(), clock=lambda: NOW, sleep=lambda _: None)
    preflight = gateway._preflight(as_of_session=as_of, observed_at_utc=NOW, provider_version="fake-sdk/1", snapshots=({"provider_update_time": update, "market_data_delay_class": delay, "regular_session_complete": True, "market_session": session},))

    assert preflight.formal_ready is False
    assert preflight.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


def test_unexpected_normalization_error_returns_atomic_incomplete_attempt() -> None:
    class InvalidClassificationProvider:
        def classification_evidence(self, stock_id: str, futu_code: str, as_of_utc: datetime):
            return None

    gateway = FutuUniverseGateway(sdk=_Sdk(), clock=lambda: NOW, sleep=lambda _: None)
    gateway._adapter = lambda: _Adapter([{"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"}])  # type: ignore[method-assign]
    attempt = gateway.collect(as_of_session=date(2026, 8, 21), observed_at_utc=NOW, classification_provider=InvalidClassificationProvider(), active_status_mapping=_mapping())

    assert attempt.attempt_status.value == "FAILED"
    assert attempt.completeness.value == "INCOMPLETE"
    assert "FUTU_SCHEMA_BLOCKER" in attempt.reason_codes


def test_gateway_has_no_evaluator_funnel_snapshot_ui_or_detector_owner() -> None:
    source = Path("src/tv_quant/pattern_finder/universe_foundation/futu_gateway.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {"evaluate_security", "build_funnel", "UniverseSnapshot", "UniverseSnapshotStore", "detect_flat_base", "render_profile_status"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    definitions = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}

    assert names.isdisjoint(forbidden)
    assert attributes.isdisjoint(forbidden)
    assert definitions.isdisjoint(forbidden)
    assert "streamlit" not in source.lower()
