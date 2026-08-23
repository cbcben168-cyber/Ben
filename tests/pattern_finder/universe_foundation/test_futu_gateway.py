"""Frozen Task 10 gateway contract tests.

All provider facts come from Task 9-shaped fake adapter batches. These tests
never create an OpenD context or make a real Futu call.
"""
from __future__ import annotations

import ast
import inspect
from dataclasses import replace
from datetime import UTC, date, datetime
from math import inf, nan
from pathlib import Path

import pytest

from tv_quant.pattern_finder.universe_foundation import (
    ActiveStatusMappingEntry,
    Decision,
    EvidenceReference,
    FutuUniverseGateway,
    QualifiedActiveStatusMapping,
    QualifiedMarketStateConsistencyContract,
    QualifiedMarketStateRelationship,
)
from tv_quant.pattern_finder.universe_foundation.evidence import SecurityClassificationEvidence
from tv_quant.pattern_finder.universe_foundation.futu_adapter import RawApiBatch, RawApiPage
from tv_quant.pattern_finder.universe_foundation import futu_gateway as futu_gateway_module
from tv_quant.pattern_finder.universe_foundation.futu_gateway import _parse_us_update_time


NOW = datetime(2026, 8, 21, 21, tzinfo=UTC)
SHA = "a" * 64
SDK_VERSION = "10.10.7008"
OPEND_VERSION = "1009"


def _mapping(*, sdk_version: str = SDK_VERSION, opend_version: str = OPEND_VERSION) -> QualifiedActiveStatusMapping:
    return QualifiedActiveStatusMapping(
        provider="FUTU",
        provider_sdk_version=sdk_version,
        opend_server_version=opend_version,
        mapping_version="active/v1",
        entries=(ActiveStatusMappingEntry("NORMAL", Decision.PASS, "ACTIVE_ALLOWED"),),
        qualified_at_utc=NOW,
        qualification_references=(EvidenceReference("qualification", "futu://qualification/active/v1", SHA),),
    )


def _market_state_contract(
    *, sdk_version: str = SDK_VERSION, opend_version: str = OPEND_VERSION, canonical_sha256: str = ""
) -> QualifiedMarketStateConsistencyContract:
    return QualifiedMarketStateConsistencyContract(
        provider="FUTU",
        provider_sdk_version=sdk_version,
        opend_server_version=opend_version,
        mapping_version="market-state-consistency/after-hours-end-v1",
        qualified_at_utc=NOW,
        qualification_references=(EvidenceReference("qualification", "futu://qualification/market-state/after-hours-end", SHA),),
        qualified_relationships=(QualifiedMarketStateRelationship("AFTER_HOURS_END", "XNYS_NON_SESSION"),),
        market_state_consistency_sha256=canonical_sha256,
    )


def test_qualified_mapping_requires_exact_dual_versions_and_hashes_both() -> None:
    mapping = _mapping()

    assert mapping.provider_sdk_version == SDK_VERSION
    assert mapping.opend_server_version == OPEND_VERSION
    assert len(mapping.active_status_mapping_sha256) == 64
    with pytest.raises(ValueError, match="10.10.7008"):
        replace(mapping, provider_sdk_version="10.09.6908", active_status_mapping_sha256="")
    with pytest.raises(ValueError, match="1009"):
        replace(mapping, opend_server_version="other-opend/1", active_status_mapping_sha256="")
    with pytest.raises(ValueError, match="non-empty"):
        replace(mapping, provider_sdk_version="", active_status_mapping_sha256="")
    with pytest.raises(ValueError, match="non-empty"):
        replace(mapping, opend_server_version="", active_status_mapping_sha256="")


def test_active_status_requires_exact_sdk_and_opend_versions() -> None:
    gateway = FutuUniverseGateway(sdk=object(), clock=lambda: NOW, sleep=lambda _: None)
    refs = (EvidenceReference("snapshot", "futu://snapshot/US.AAA", SHA),)

    qualified = gateway.normalized_active_status(
        delisting=False,
        suspension=False,
        raw_status="NORMAL",
        evidence_references=refs,
        mapping=_mapping(),
        provider="FUTU",
        provider_sdk_version=SDK_VERSION,
        opend_server_version=OPEND_VERSION,
    )
    assert qualified.decision is Decision.PASS

    for sdk_version, opend_version in (("other-sdk/1", OPEND_VERSION), (SDK_VERSION, "other-opend/1")):
        decision = gateway.normalized_active_status(
            delisting=False,
            suspension=False,
            raw_status="NORMAL",
            evidence_references=refs,
            mapping=_mapping(),
            provider="FUTU",
            provider_sdk_version=sdk_version,
            opend_server_version=opend_version,
        )
        assert decision.decision is Decision.UNKNOWN
        assert decision.reason_code == "ACTIVE_STATUS_UNKNOWN"

    assert gateway.normalized_active_status(
        delisting=True,
        suspension=False,
        raw_status="NORMAL",
        evidence_references=refs,
        mapping=_mapping(),
        provider="FUTU",
        provider_sdk_version="other-sdk/1",
        opend_server_version="other-opend/1",
    ).reason_code == "DELISTED"
    assert gateway.normalized_active_status(
        delisting=False,
        suspension=True,
        raw_status="NORMAL",
        evidence_references=refs,
        mapping=_mapping(),
        provider="FUTU",
        provider_sdk_version=SDK_VERSION,
        opend_server_version=OPEND_VERSION,
    ).reason_code == "SUSPENDED_AS_OF_SNAPSHOT"
    assert gateway.normalized_active_status(
        delisting=False,
        suspension=False,
        raw_status="UNKNOWN_STATUS",
        evidence_references=refs,
        mapping=_mapping(),
        provider="FUTU",
        provider_sdk_version=SDK_VERSION,
        opend_server_version=OPEND_VERSION,
    ).decision is Decision.UNKNOWN
    with pytest.raises(ValueError, match="non-empty"):
        replace(_mapping(), entries=(), active_status_mapping_sha256="")


@pytest.mark.parametrize("value", (True, False, -1, nan, inf, -inf, "0", None))
def test_collect_rejects_invalid_runtime_window_before_provider_acquisition(value: object) -> None:
    adapter = _Adapter()
    gateway = _gateway(adapter)

    with pytest.raises(ValueError, match="runtime_evidence_window_seconds"):
        gateway.collect(
            as_of_session=date(2026, 8, 21),
            observed_at_utc=NOW,
            classification_provider=_ClassificationProvider(),
            active_status_mapping=_mapping(),
            market_state_consistency_contract=_market_state_contract(),
            runtime_evidence_window_seconds=value,  # type: ignore[arg-type]
        )

    assert adapter.calls == []


def test_collect_signature_requires_keyword_only_default_free_runtime_window() -> None:
    parameters = inspect.signature(FutuUniverseGateway.collect).parameters
    parameter = parameters["runtime_evidence_window_seconds"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty
    assert parameters["market_state_consistency_contract"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["market_state_consistency_contract"].default is inspect.Parameter.empty


class _Adapter:
    def __init__(
        self,
        *,
        discovery_rows: list[dict[str, object]] | None = None,
        runtime_batches: tuple[RawApiBatch, ...] | None = None,
        state_rows: list[object] | None = None,
        snapshot_update_time: str = "2026-08-21 16:00:00",
        snapshot_update_times: dict[str, str] | None = None,
        qot_events: list[dict[str, object]] | None = None,
        sdk_version: str = SDK_VERSION,
        opend_version: str = OPEND_VERSION,
    ) -> None:
        self.discovery_rows = discovery_rows or [
            {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"}
        ]
        self.runtime_batches = runtime_batches
        self.state_rows = state_rows
        self.snapshot_update_time = snapshot_update_time
        self.snapshot_update_times = snapshot_update_times or {}
        self.qot_events = qot_events or []
        self.sdk_version = sdk_version
        self.opend_version = opend_version
        self.calls: list[tuple[str, object]] = []
        self.last_snapshot_rows: list[dict[str, object]] = []

    @staticmethod
    def _batch(endpoint: str, response: dict[str, object]) -> RawApiBatch:
        return RawApiBatch(endpoint, 1, {}, response, SHA, "b" * 64, 0, "SUCCESS", NOW)

    def discover_cash_securities(self):
        self.calls.append(("discover_cash_securities", None))
        return (self._batch("discover_cash_securities", {"rows": self.discovery_rows}),)

    def screen_all_pages(self):
        self.calls.append(("screen_all_pages", None))
        rows = [
            {"code": row["code"], "name": "Example", "industry": "Technology", "price": "10.00", "market_cap": "1000000000.00", "avg_turnover": "20000000.00", "listed_days": 300}
            for row in self.discovery_rows
        ]
        return (RawApiPage("screen_all_pages", 1, {"page_from": 0}, True, {}, {"rows": rows}, SHA, "c" * 64, 0, "SUCCESS", NOW),)

    def market_snapshots(self, codes):
        self.calls.append(("market_snapshots", tuple(codes)))
        rows = [
            {
                "code": code,
                "suspension": False,
                "sec_status": "NORMAL",
                "update_time": self.snapshot_update_times.get(code, self.snapshot_update_time),
            }
            for code in codes
        ]
        self.last_snapshot_rows = rows
        return (self._batch("market_snapshots", {"rows": rows}),)

    def market_states(self, codes):
        self.calls.append(("market_states", tuple(codes)))
        rows = self.state_rows if self.state_rows is not None else [{"code": code, "market_state": "AFTER_HOURS_END"} for code in codes]
        return (self._batch("market_states", {"rows": rows}),)

    def owner_plates(self, codes):
        self.calls.append(("owner_plates", tuple(codes)))
        return (self._batch("owner_plates", {"rows": []}),)

    def collect_runtime_evidence(self, *, notification_window_seconds: float):
        self.calls.append(("collect_runtime_evidence", notification_window_seconds))
        if self.runtime_batches is not None:
            return self.runtime_batches
        return (
            self._batch("runtime_sdk_version", {"sdk_version": self.sdk_version}),
            self._batch("global_state", {"server_ver": self.opend_version}),
            self._batch("qot_right_capture", {"events": self.qot_events}),
        )


class _ClassificationProvider:
    def classification_evidence(self, stock_id: str, futu_code: str, as_of_utc: datetime):
        return (
            SecurityClassificationEvidence(
                normalized_class="COMMON_STOCK", provider="APPROVED_SECURITY_MASTER", provider_value="Common",
                observed_at_utc=as_of_utc, source_version="master/v1", source_record_sha256="b" * 64,
                confidence="AUTHORITATIVE", notes="typed",
                reference=EvidenceReference("master", f"master://{stock_id}", "b" * 64), verified_by=None,
            ),
        )


def _gateway(adapter: _Adapter) -> FutuUniverseGateway:
    gateway = FutuUniverseGateway(sdk=object(), clock=lambda: NOW, sleep=lambda _: None)
    gateway._adapter = lambda: adapter  # type: ignore[method-assign]
    return gateway


def _collect(
    adapter: _Adapter,
    *,
    window: float = 0.0,
    mapping: QualifiedActiveStatusMapping | None = None,
    market_state_contract: QualifiedMarketStateConsistencyContract | None = None,
):
    return _gateway(adapter).collect(
        as_of_session=date(2026, 8, 21), observed_at_utc=NOW,
        classification_provider=_ClassificationProvider(), active_status_mapping=mapping or _mapping(),
        market_state_consistency_contract=market_state_contract or _market_state_contract(),
        runtime_evidence_window_seconds=window,
    )


def test_collect_passes_window_unchanged_binds_it_to_failed_attempt_and_hash() -> None:
    first_adapter, second_adapter = _Adapter(), _Adapter()
    first = _collect(first_adapter, window=0.0)
    second = _collect(second_adapter, window=5.0)

    assert ("collect_runtime_evidence", 0.0) in first_adapter.calls
    assert ("collect_runtime_evidence", 5.0) in second_adapter.calls
    assert first.runtime_evidence_window_seconds == 0.0
    assert second.runtime_evidence_window_seconds == 5.0
    assert first.attempt_id != second.attempt_id
    assert first.attempt_status.value == "FAILED"
    assert first.completeness.value == "INCOMPLETE"


def test_collect_consumes_task9_runtime_and_market_state_raw_batches_only() -> None:
    adapter = _Adapter(qot_events=[])
    attempt = _collect(adapter)

    assert ("market_states", ("US.AAA",)) in adapter.calls
    assert {batch.endpoint for batch in attempt.batches} >= {"runtime_sdk_version", "global_state", "qot_right_capture", "market_states"}
    assert attempt.market_data_delay_class == "UNKNOWN"
    assert attempt.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)
    assert attempt.market_state_consistency_contract == _market_state_contract()
    assert attempt.realtime_capability_probes == ()


@pytest.mark.parametrize("missing_endpoint", ("runtime_sdk_version", "global_state", "qot_right_capture"))
def test_runtime_evidence_missing_fixed_endpoint_fails_closed(missing_endpoint: str) -> None:
    complete = _Adapter().collect_runtime_evidence(notification_window_seconds=0.0)
    adapter = _Adapter(runtime_batches=tuple(batch for batch in complete if batch.endpoint != missing_endpoint))

    attempt = _collect(adapter)

    assert attempt.attempt_status.value == "FAILED"
    assert attempt.completeness.value == "INCOMPLETE"
    assert "FUTU_SCHEMA_BLOCKER" in attempt.reason_codes


@pytest.mark.parametrize(
    "events",
    [
        [{}],
        [{"notify_type": "QOT_RIGHT", "sub_type": "EVENT", "msg": {}}],
        [{"notify_type": "QOT_RIGHT", "sub_type": "EVENT", "msg": None}],
    ],
)
def test_nonempty_qot_right_events_require_task9_raw_event_shape(events: list[dict[str, object]]) -> None:
    attempt = _collect(_Adapter(qot_events=events))

    assert attempt.attempt_status.value == "FAILED"
    assert "FUTU_SCHEMA_BLOCKER" in attempt.reason_codes


def test_qot_right_event_with_raw_us_right_field_stays_uninterpreted() -> None:
    attempt = _collect(_Adapter(qot_events=[{"notify_type": "QOT_RIGHT", "sub_type": "EVENT", "msg": {"us_qot_right": None}}]))

    assert attempt.market_data_delay_class == "UNKNOWN"
    assert attempt.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


@pytest.mark.parametrize("window", (0.0, 5.0, 15.0))
@pytest.mark.parametrize("events", ([], [{"notify_type": "QOT_RIGHT", "sub_type": "EVENT", "msg": {"us_qot_right": "LEVEL2"}}]))
def test_qot_right_is_change_event_audit_only_for_every_window(window: float, events: list[dict[str, object]]) -> None:
    attempt = _collect(_Adapter(qot_events=events), window=window)

    assert attempt.market_data_delay_class == "UNKNOWN"
    assert attempt.preflight.formal_ready is False
    assert attempt.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


def test_runtime_version_mismatch_is_active_unknown_without_fallback() -> None:
    attempt = _collect(_Adapter(sdk_version="10.09.6908"))

    assert attempt.prerequisites[0].active_status is not None
    assert attempt.prerequisites[0].active_status.decision is Decision.UNKNOWN
    assert attempt.prerequisites[0].active_status.reason_code == "ACTIVE_STATUS_UNKNOWN"


def test_snapshot_fixture_has_no_synthetic_freshness_fields_and_uses_new_york_time() -> None:
    adapter = _Adapter()
    attempt = _collect(adapter)
    row = adapter.last_snapshot_rows[0]

    assert "market_data_delay_class" not in row
    assert "regular_session_complete" not in row
    assert "market_session" not in row
    assert attempt.provider_update_time == datetime(2026, 8, 21, 20, tzinfo=UTC)


def test_us_snapshot_time_accepts_optional_fractional_seconds_as_new_york_wall_time() -> None:
    assert _parse_us_update_time("2026-08-21 19:59:59.839") == datetime(2026, 8, 21, 23, 59, 59, 839000, tzinfo=UTC)
    assert _parse_us_update_time("2026-12-01 16:00:00") == datetime(2026, 12, 1, 21, tzinfo=UTC)


@pytest.mark.parametrize("value", ("2026-11-01 01:30:00", "2026-03-08 02:30:00", "not-a-time", "2026-08-21T16:00:00+00:00"))
def test_us_snapshot_time_rejects_ambiguous_nonexistent_and_non_contract_values(value: str) -> None:
    assert _parse_us_update_time(value) is None


def _timestamp_only_preflight(
    monkeypatch: pytest.MonkeyPatch,
    update_times: tuple[str, ...],
    *,
    observed_at_utc: datetime = NOW,
):
    snapshots = tuple(
        {"code": f"US.{index}", "update_time": value}
        for index, value in enumerate(update_times, start=1)
    )
    market_states = tuple(
        {"code": row["code"], "market_state": "AFTER_HOURS_END"}
        for row in snapshots
    )
    with monkeypatch.context() as authority:
        authority.setattr(
            futu_gateway_module,
            "PROVIDER_OR_ACCOUNT_LEVEL_CURRENT_QUOTE_RIGHT_AUTHORITY",
            "QUALIFIED",
        )
        authority.setattr(futu_gateway_module, "FORMAL_FRESHNESS_AUTHORITY", "QUALIFIED")
        return _gateway(_Adapter())._preflight(
            as_of_session=date(2026, 8, 21),
            observed_at_utc=observed_at_utc,
            provider_sdk_version=SDK_VERSION,
            opend_server_version=OPEND_VERSION,
            snapshots=snapshots,
            market_states=market_states,
            market_state_consistency_contract=_market_state_contract(),
        )


def test_multi_security_different_valid_timestamps_use_oldest_watermark_without_extra_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timestamp_preflight = _timestamp_only_preflight(
        monkeypatch,
        ("2026-08-21 16:00:00", "2026-08-21 16:00:01"),
    )

    assert timestamp_preflight.provider_update_time == datetime(2026, 8, 21, 20, tzinfo=UTC)
    assert timestamp_preflight.formal_ready is True
    assert timestamp_preflight.reason_codes == ()

    adapter = _Adapter(
        discovery_rows=[
            {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
            {"stock_id": "2", "code": "US.BBB", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
        ],
        snapshot_update_times={
            "US.AAA": "2026-08-21 16:00:00",
            "US.BBB": "2026-08-21 16:00:01",
        },
    )
    attempt = _collect(adapter)

    assert attempt.preflight.provider_update_time == datetime(2026, 8, 21, 20, tzinfo=UTC)
    assert attempt.attempt_status.value == "FAILED"
    assert attempt.completeness.value == "INCOMPLETE"
    assert attempt.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


def test_multi_security_one_invalid_timestamp_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    preflight = _timestamp_only_preflight(
        monkeypatch,
        ("2026-08-21 16:00:00", "not-a-time"),
    )

    assert preflight.provider_update_time is None
    assert preflight.formal_ready is False
    assert preflight.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


def test_multi_security_any_future_timestamp_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    preflight = _timestamp_only_preflight(
        monkeypatch,
        ("2026-08-21 16:00:00", "2026-08-21 17:00:01"),
    )

    assert preflight.provider_update_time == datetime(2026, 8, 21, 20, tzinfo=UTC)
    assert preflight.formal_ready is False
    assert preflight.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


def test_multi_security_any_stale_timestamp_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    preflight = _timestamp_only_preflight(
        monkeypatch,
        ("2026-08-21 15:59:59", "2026-08-21 16:00:01"),
    )

    assert preflight.provider_update_time == datetime(2026, 8, 21, 19, 59, 59, tzinfo=UTC)
    assert preflight.formal_ready is False
    assert preflight.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


def test_multi_security_same_valid_timestamp_preserves_existing_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    preflight = _timestamp_only_preflight(
        monkeypatch,
        ("2026-08-21 16:00:00", "2026-08-21 16:00:00"),
    )

    assert preflight.provider_update_time == datetime(2026, 8, 21, 20, tzinfo=UTC)
    assert preflight.formal_ready is True
    assert preflight.reason_codes == ()


def test_missing_duplicate_null_or_unqualified_market_state_rows_fail_closed() -> None:
    for rows in (
        [],
        [{"code": "US.AAA", "market_state": "AFTER_HOURS_END"}, {"code": "US.AAA", "market_state": "AFTER_HOURS_END"}],
        [{"code": "US.AAA"}],
        [{"code": "US.AAA", "market_state": None}],
        ["not-a-mapping"],
    ):
        attempt = _collect(_Adapter(state_rows=rows))
        assert attempt.attempt_status.value == "FAILED"
        assert "UNIVERSE_FRESHNESS_BLOCKER" in attempt.reason_codes


@pytest.mark.parametrize(
    "raw_state",
    ("MORNING", "AFTERNOON", "CLOSED", "PRE_MARKET_BEGIN", "PRE_MARKET_END", "AFTER_HOURS_BEGIN", "OVERNIGHT", "NEW_STATE"),
)
def test_raw_market_state_is_consumed_and_every_unqualified_enum_fails_closed(raw_state: str) -> None:
    attempt = _collect(_Adapter(state_rows=[{"code": "US.AAA", "market_state": raw_state}]))

    assert attempt.attempt_status.value == "FAILED"
    assert attempt.completeness.value == "INCOMPLETE"
    assert attempt.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


def test_market_state_contract_exact_versions_hash_and_calendar_relationship() -> None:
    contract = _market_state_contract()

    assert len(contract.canonical_sha256) == 64
    assert contract.qualified_relationships[0].raw_market_state == "AFTER_HOURS_END"
    with pytest.raises(ValueError, match="tamper"):
        _market_state_contract(canonical_sha256="f" * 64)

    with pytest.raises(ValueError, match="10.10.7008"):
        _market_state_contract(sdk_version="10.09.6908")
    with pytest.raises(ValueError, match="1009"):
        _market_state_contract(opend_version="other-opend")

    for adapter in (
        _Adapter(sdk_version="10.09.6908"),
        _Adapter(opend_version="other-opend"),
    ):
        attempt = _collect(adapter)
        assert attempt.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)

    in_session = _gateway(_Adapter(snapshot_update_time="2026-08-21 15:00:00")).collect(
        as_of_session=date(2026, 8, 20),
        observed_at_utc=datetime(2026, 8, 21, 19, tzinfo=UTC),
        classification_provider=_ClassificationProvider(),
        active_status_mapping=_mapping(),
        market_state_consistency_contract=_market_state_contract(),
        runtime_evidence_window_seconds=0.0,
    )
    assert in_session.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)


def test_quote_probe_cardinality_is_not_bound_to_universe_and_formal_stays_closed() -> None:
    adapter = _Adapter(discovery_rows=[
        {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
        {"stock_id": "2", "code": "US.BBB", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
    ])

    attempt = _collect(adapter)

    assert attempt.realtime_capability_probes == ()
    assert all(call[0] != "probe_realtime_quote_capability" for call in adapter.calls)
    assert attempt.attempt_status.value == "FAILED"
    assert attempt.completeness.value == "INCOMPLETE"
    assert attempt.reason_codes == ("UNIVERSE_FRESHNESS_BLOCKER",)
    assert len(attempt.evidence) == 2
    assert len(attempt.prerequisites) == 2


def test_optional_probe_attempt_binding_is_sensitive_to_request_code_and_time() -> None:
    def probe(code: str, request_hash: str, acquired_at: datetime) -> RawApiBatch:
        return RawApiBatch(
            "realtime_quote_capability_probe",
            1,
            {"code": code, "subtype": "QUOTE", "subscribe_push": False},
            {"capability_verdict": "PROVEN_SCOPE_LIMITED"},
            request_hash,
            "e" * 64,
            0,
            "SUCCESS",
            acquired_at,
        )

    gateway = _gateway(_Adapter())
    common = {
        "as_of_session": date(2026, 8, 21),
        "observed_at_utc": NOW,
        "mapping": _mapping(),
        "market_state_contract": _market_state_contract(),
        "runtime_evidence_window_seconds": 0.0,
        "reasons": ("UNIVERSE_FRESHNESS_BLOCKER",),
        "prerequisites_hash": "d" * 64,
        "batches": (),
    }
    first = gateway._attempt_id(**common, realtime_capability_probes=(probe("US.AAPL", "1" * 64, NOW),))
    changed_code = gateway._attempt_id(**common, realtime_capability_probes=(probe("US.MSFT", "2" * 64, NOW),))
    changed_time = gateway._attempt_id(**common, realtime_capability_probes=(probe("US.AAPL", "1" * 64, NOW.replace(minute=1)),))

    assert len({first, changed_code, changed_time}) == 3

    attempt = _collect(_Adapter())
    invalid_probe = probe("US.AAPL", "1" * 64, NOW)
    invalid_probe = replace(invalid_probe, endpoint="market_states")
    with pytest.raises(ValueError, match="realtime_quote_capability_probe"):
        replace(attempt, realtime_capability_probes=(invalid_probe,))


def test_identity_conflicts_remain_distinct_and_no_partial_formal_attempt_is_created() -> None:
    same_stock = _collect(_Adapter(discovery_rows=[
        {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
        {"stock_id": "1", "code": "US.AAB", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
    ]))
    assert same_stock.attempt_status.value == "FAILED"
    assert [item.identity.decision for item in same_stock.prerequisites] == [Decision.UNKNOWN, Decision.UNKNOWN]

    same_code = _collect(_Adapter(discovery_rows=[
        {"stock_id": "1", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
        {"stock_id": "2", "code": "US.AAA", "delisting": False, "exchange_type": "NASDAQ", "stock_type": "STOCK"},
    ]))
    assert same_code.attempt_status.value == "FAILED"
    assert same_code.completeness.value == "INCOMPLETE"
    assert "UNIVERSE_IDENTITY_BLOCKER" in same_code.reason_codes
    assert same_code.prerequisites == ()


def test_gateway_has_no_direct_task9_sdk_acquisition_or_downstream_owner() -> None:
    source = Path("src/tv_quant/pattern_finder/universe_foundation/futu_gateway.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    forbidden = {"get_market_state", "get_global_state", "set_handler", "subscribe", "unsubscribe", "evaluate_security", "build_funnel", "UniverseSnapshot", "UniverseSnapshotStore", "detect_flat_base"}

    assert attributes.isdisjoint(forbidden)
    assert "openfigi" not in source.lower()
