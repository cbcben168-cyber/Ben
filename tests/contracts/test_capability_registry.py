from __future__ import annotations

from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import socket
import sys
from types import ModuleType
from urllib import request

import pytest

from tv_quant.contracts.capability_registry import (
    CapabilityRecord,
    CapabilityRegistry,
    capability_snapshot_hash,
    load_capability_registry,
)
from tv_quant.contracts.execution_assumptions import ExecutionAssumptions
from tv_quant.contracts.status_codes import BlockerCode


REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "capability-registry-v2.1.json"
)


class _CallableString(str):
    def __call__(self) -> None:
        return None


def _record(**overrides: object) -> dict[str, object]:
    record: dict[str, object] = {
        "capability_id": "test.capability",
        "version": "v2.1",
        "implementation_status": "not_implemented",
        "supported_market": ["US_EQUITY"],
        "supported_timeframes": ["1d"],
        "provider": None,
        "required_dependencies": [],
        "formal_status": "unavailable",
        "structural_availability": "available",
        "implementation_availability": "unavailable",
        "formal_eligibility": "not_eligible",
        "smoke_only_status": "not_smoke_only",
        "blocker_code": BlockerCode.ENGINE_CAPABILITY_BLOCKER.value,
        "evidence": ["boundary:frozen-v2.1-design"],
        "last_verified": "2026-07-27",
        "implementation_owner": "tv_quant.contracts",
    }
    record.update(overrides)
    return record


def _payload(*records: dict[str, object]) -> dict[str, object]:
    return {"schema_version": "v2.1", "capabilities": list(records or (_record(),))}


def _replace_record(
    payload: dict[str, object], index: int = 0, **overrides: object
) -> dict[str, object]:
    copied = json.loads(json.dumps(payload))
    copied["capabilities"][index].update(overrides)
    return copied


def _execution_assumptions(snapshot_hash: str) -> ExecutionAssumptions:
    return ExecutionAssumptions(
        initial_capital_policy="100000 USD",
        fill_timing="next_bar_open",
        session_policy={
            "timezone": "America/New_York",
            "regular_hours_only": True,
            "calendar_id": "XNYS",
        },
        optimization_policy="false",
        report_language="zh-CN",
        cost_profile_id="phase1.bps",
        corporate_action_profile_id="adjusted_ohlcv",
        benchmark_protocol_id="buy_and_hold",
        capability_snapshot_hash=snapshot_hash,
        schema_version="v2.1",
        compiler_version="v2.1",
        normalizer_version="v2.1",
        benchmark_protocol_version="v2.1",
        engine_status="NOT_IMPLEMENTED",
        plugin=None,
    )


def test_phase1_ema_is_only_formal_golden_capability() -> None:
    registry = load_capability_registry(REGISTRY_PATH)

    formal = tuple(
        record
        for record in registry.capabilities
        if record.formal_eligibility == "eligible"
    )

    assert registry.schema_version == "v2.1"
    assert tuple(record.capability_id for record in formal) == (
        "phase1.ema.daily.golden",
    )
    assert registry.require_formal(
        "phase1.ema.daily.golden", "v2.1"
    ).formal_status == "formal_verified"


def test_v22a_data_foundation_records_are_present_but_not_formal() -> None:
    registry = load_capability_registry(REGISTRY_PATH)

    for capability_id in (
        "market-data.local-csv.daily",
        "market-data.local-parquet.daily",
        "market-data.yfinance-smoke.local",
    ):
        record = registry.require(capability_id, "v2.2a")
        assert record.formal_status == "unavailable"
        assert record.blocker_code is BlockerCode.DATA_CAPABILITY_BLOCKER


def test_symbol_structural_support_is_not_phase1_execution_support() -> None:
    registry = load_capability_registry(REGISTRY_PATH)
    phase1 = registry.require("phase1.ema.daily.golden", "v2.1")
    futu = registry.require("futu.daily.current", "v2.1")

    assert phase1.supported_market == ("QQQ", "SPY")
    assert futu.supported_market == ("US_EQUITY",)
    assert futu.structural_availability == "available"
    assert futu.formal_eligibility == "not_eligible"


def test_vectorbt_intraday_dividend_and_plugin_are_unavailable() -> None:
    registry = load_capability_registry(REGISTRY_PATH)
    expected = {
        "vectorbt.daily.main": BlockerCode.ENGINE_CAPABILITY_BLOCKER,
        "intraday.15m.30m.60m": BlockerCode.DATA_CAPABILITY_BLOCKER,
        "corporate_actions.cash_dividend": BlockerCode.CORPORATE_ACTION_DATA_BLOCKER,
        "plugin.execution.sandbox": BlockerCode.PLUGIN_VALIDATION_BLOCKER,
    }

    for capability_id, blocker in expected.items():
        record = registry.require(capability_id, "v2.1")
        assert record.formal_status == "unavailable"
        assert record.implementation_availability == "unavailable"
        assert record.formal_eligibility == "not_eligible"
        assert record.blocker_code is blocker


def test_futu_daily_is_not_live_verified_and_not_formal_eligible() -> None:
    record = load_capability_registry(REGISTRY_PATH).require(
        "futu.daily.current", "v2.1"
    )

    assert record.implementation_status == "implemented"
    assert record.formal_status == "not_live_verified"
    assert record.formal_eligibility == "not_eligible"
    assert record.smoke_only_status == "smoke_only"
    assert record.blocker_code is None


def test_require_formal_rejects_not_live_verified() -> None:
    registry = load_capability_registry(REGISTRY_PATH)

    with pytest.raises(ValueError, match="not formal-eligible"):
        registry.require_formal("futu.daily.current", "v2.1")


def test_duplicate_id_and_unknown_status_are_rejected() -> None:
    duplicate = _payload(_record(), _record())
    with pytest.raises(ValueError, match="duplicate capability"):
        CapabilityRegistry(duplicate)

    unknown = _payload(_record(implementation_status="ready"))
    with pytest.raises(ValueError, match="implementation_status"):
        CapabilityRegistry(unknown)


def test_formal_status_with_blocker_is_rejected() -> None:
    payload = _payload(
        _record(
            implementation_status="implemented",
            implementation_availability="available",
            formal_status="formal_verified",
            formal_eligibility="eligible",
            blocker_code=BlockerCode.ENGINE_CAPABILITY_BLOCKER.value,
        )
    )

    with pytest.raises(ValueError, match="formal record cannot carry blocker"):
        CapabilityRegistry(payload)


def test_snapshot_hash_is_deterministic() -> None:
    first = _payload(
        _record(capability_id="z.capability"),
        _record(capability_id="a.capability"),
    )
    second = {
        "capabilities": [
            dict(reversed(list(first["capabilities"][1].items()))),
            dict(reversed(list(first["capabilities"][0].items()))),
        ],
        "schema_version": "v2.1",
    }

    first_registry = CapabilityRegistry(first)
    second_registry = CapabilityRegistry(second)

    assert tuple(
        record.capability_id for record in first_registry.capabilities
    ) == ("a.capability", "z.capability")
    assert first_registry.snapshot_payload() == second_registry.snapshot_payload()
    assert capability_snapshot_hash(first_registry) == capability_snapshot_hash(
        second_registry
    )
    assert first_registry.snapshot_hash() == capability_snapshot_hash(first_registry)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("implementation_status", "unknown"),
        ("formal_status", "ready"),
        ("structural_availability", "structural_only"),
        ("implementation_availability", "not_live_verified"),
        ("formal_eligibility", "formal"),
        ("smoke_only_status", "test_only"),
    ),
)
def test_all_status_dimensions_are_restricted(field: str, value: str) -> None:
    with pytest.raises(ValueError, match=field):
        CapabilityRegistry(_payload(_record(**{field: value})))


@pytest.mark.parametrize(
    "mutation",
    (
        lambda payload: payload.update({"unknown": True}),
        lambda payload: payload["capabilities"][0].update({"unknown": True}),
        lambda payload: payload.pop("schema_version"),
        lambda payload: payload["capabilities"][0].pop("provider"),
        lambda payload: payload["capabilities"][0].update({"capability_id": ""}),
    ),
)
def test_strict_fields_missing_fields_and_empty_ids_are_rejected(mutation) -> None:
    payload = _payload()
    mutation(payload)

    with pytest.raises(ValueError):
        CapabilityRegistry(payload)


def test_duplicate_json_object_field_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "registry.json"
    path.write_text(
        '{"schema_version":"v2.1","schema_version":"v2.1","capabilities":[]}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON field"):
        load_capability_registry(path)


@pytest.mark.parametrize(
    "forbidden",
    (
        lambda: None,
        socket,
        CapabilityRecord,
    ),
)
def test_callable_module_and_class_values_are_rejected(forbidden: object) -> None:
    payload = _payload(_record(evidence=[forbidden]))

    with pytest.raises(ValueError, match="string"):
        CapabilityRegistry(payload)


def test_validated_registry_and_snapshot_are_deeply_immutable() -> None:
    source = _payload()
    registry = CapabilityRegistry(source)
    source["capabilities"][0]["evidence"].append("late-mutation")

    assert registry.capabilities[0].evidence == ("boundary:frozen-v2.1-design",)
    with pytest.raises(FrozenInstanceError):
        registry.capabilities[0].capability_id = "changed"
    with pytest.raises(TypeError):
        registry.snapshot_payload()["schema_version"] = "changed"
    with pytest.raises(TypeError):
        registry.snapshot_payload()["capabilities"][0]["version"] = "changed"


def test_snapshot_hash_changes_with_content_status_scope_and_version() -> None:
    base = _payload()
    mutations = (
        _replace_record(base, evidence=["boundary:different-evidence"]),
        _replace_record(base, implementation_status="not_verified"),
        _replace_record(base, supported_market=["SPY"]),
        _replace_record(base, version="v2.2"),
    )
    base_hash = capability_snapshot_hash(CapabilityRegistry(base))

    assert all(
        capability_snapshot_hash(CapabilityRegistry(payload)) != base_hash
        for payload in mutations
    )


def test_snapshot_omits_time_path_pid_and_mtime_noise() -> None:
    first = CapabilityRegistry(_payload(_record(last_verified="2026-07-27")))
    second = CapabilityRegistry(_payload(_record(last_verified="2099-12-31")))
    serialized = json.dumps(first.snapshot_payload(), default=dict)

    assert "last_verified" not in serialized
    assert "timestamp" not in serialized
    assert "path" not in serialized
    assert "pid" not in serialized.lower()
    assert "mtime" not in serialized
    assert capability_snapshot_hash(first) == capability_snapshot_hash(second)


def test_inconsistent_availability_and_smoke_only_formal_records_are_rejected() -> None:
    not_implemented_formal = _payload(
        _record(
            formal_status="formal_verified",
            formal_eligibility="eligible",
            blocker_code=None,
        )
    )
    smoke_formal = _payload(
        _record(
            implementation_status="implemented",
            implementation_availability="available",
            formal_status="formal_verified",
            formal_eligibility="eligible",
            smoke_only_status="smoke_only",
            blocker_code=None,
        )
    )

    with pytest.raises(ValueError, match="implemented"):
        CapabilityRegistry(not_implemented_formal)
    with pytest.raises(ValueError, match="smoke-only"):
        CapabilityRegistry(smoke_formal)


def test_loader_has_no_network_provider_vectorbt_or_backtest_side_effects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("external or execution behavior is forbidden")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(request, "urlopen", forbidden)
    before = set(sys.modules)

    registry = load_capability_registry(REGISTRY_PATH)

    newly_imported = set(sys.modules) - before
    assert registry.capabilities
    assert not any(name == "futu" or name.startswith("futu.") for name in newly_imported)
    assert not any(
        name == "vectorbt" or name.startswith("vectorbt.") for name in newly_imported
    )
    assert "tv_quant.strategy" not in newly_imported


def test_snapshot_hash_satisfies_execution_assumptions_boundary() -> None:
    snapshot_hash = capability_snapshot_hash(load_capability_registry(REGISTRY_PATH))

    assumptions = _execution_assumptions(snapshot_hash)

    assert assumptions.capability_snapshot_hash == snapshot_hash
    assert len(snapshot_hash) == 64
    assert snapshot_hash == snapshot_hash.lower()


def test_registry_constructor_rejects_non_mapping_and_non_object_records() -> None:
    with pytest.raises(ValueError, match="mapping"):
        CapabilityRegistry([])
    with pytest.raises(ValueError, match="record"):
        CapabilityRegistry({"schema_version": "v2.1", "capabilities": [ModuleType("x")]})


def test_scope_reordering_does_not_change_snapshot_or_hash() -> None:
    first = CapabilityRegistry(
        _payload(
            _record(
                supported_market=["SPY", "QQQ"],
                supported_timeframes=["1d", "15m"],
            )
        )
    )
    reordered = CapabilityRegistry(
        _payload(
            _record(
                supported_market=["QQQ", "SPY"],
                supported_timeframes=["15m", "1d"],
            )
        )
    )

    assert first.snapshot_payload() == reordered.snapshot_payload()
    assert capability_snapshot_hash(first) == capability_snapshot_hash(reordered)


def test_duplicate_scope_values_are_rejected() -> None:
    with pytest.raises(ValueError, match="supported_market.*unique"):
        CapabilityRegistry(_payload(_record(supported_market=["SPY", "SPY"])))
    with pytest.raises(ValueError, match="supported_timeframes.*unique"):
        CapabilityRegistry(_payload(_record(supported_timeframes=["1d", "1d"])))


@pytest.mark.parametrize("field", ("supported_market", "supported_timeframes"))
def test_empty_scope_values_are_rejected(field: str) -> None:
    with pytest.raises(ValueError, match=f"{field}.*non-empty"):
        CapabilityRegistry(_payload(_record(**{field: []})))


@pytest.mark.parametrize(
    "machine_local_evidence",
    (
        r"path:C:\Users\alice\registry.json",
        "pid:4242",
        "hostname:DESKTOP-LOCAL",
        "username:alice",
        "timestamp:2026-07-27T12:34:56Z",
    ),
)
def test_machine_local_evidence_is_rejected(machine_local_evidence: str) -> None:
    with pytest.raises(ValueError, match="evidence.*stable"):
        CapabilityRegistry(_payload(_record(evidence=[machine_local_evidence])))


def test_machine_local_implementation_owner_is_rejected() -> None:
    with pytest.raises(ValueError, match="implementation_owner"):
        CapabilityRegistry(
            _payload(_record(implementation_owner="hostname:DESKTOP-LOCAL"))
        )


@pytest.mark.parametrize(
    "payload",
    (
        {
            _CallableString("schema_version"): "v2.1",
            "capabilities": [_record()],
        },
        _payload(_record(capability_id=_CallableString("callable.capability"))),
        _payload(_record(supported_market=[_CallableString("SPY")])),
        _payload(
            _record(
                blocker_code=_CallableString(
                    BlockerCode.ENGINE_CAPABILITY_BLOCKER.value
                )
            )
        ),
    ),
)
def test_callable_string_subclasses_are_rejected(payload: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="built-in string"):
        CapabilityRegistry(payload)


@pytest.mark.parametrize(
    ("overrides", "message"),
    (
        (
            {"formal_status": "not_live_verified"},
            "not_live_verified.*implemented",
        ),
        (
            {
                "implementation_status": "not_verified",
                "formal_status": "not_live_verified",
            },
            "not_live_verified.*implemented",
        ),
        (
            {
                "implementation_status": "implemented",
                "formal_status": "unavailable",
            },
            "implemented.*formal_verified or not_live_verified",
        ),
        (
            {
                "implementation_status": "implemented",
                "implementation_availability": "available",
                "formal_status": "not_live_verified",
                "smoke_only_status": "not_smoke_only",
                "blocker_code": None,
            },
            "not_live_verified.*smoke_only",
        ),
        (
            {
                "implementation_status": "implemented",
                "implementation_availability": "available",
                "formal_status": "not_live_verified",
                "smoke_only_status": "smoke_only",
            },
            "not_live_verified.*blocker",
        ),
        (
            {"smoke_only_status": "smoke_only"},
            "unavailable.*not_smoke_only",
        ),
        (
            {
                "implementation_status": "implemented",
                "implementation_availability": "available",
                "formal_status": "formal_verified",
                "formal_eligibility": "not_eligible",
                "blocker_code": None,
            },
            "formal_verified.*formal-eligible",
        ),
    ),
    ids=(
        "not-implemented-not-live",
        "not-verified-not-live",
        "implemented-unavailable",
        "not-live-not-smoke",
        "not-live-with-blocker",
        "unavailable-smoke-only",
        "formal-verified-not-eligible",
    ),
)
def test_status_coherence_matrix_rejects_dishonest_combinations(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        CapabilityRegistry(_payload(_record(**overrides)))
