"""End-to-end checks for the public V2.1 contract gate."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, replace
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from tv_quant.adapters.phase1_config_adapter import (
    Phase1ToV2AdapterResult,
    adapt_phase1_to_v2,
)
import tv_quant.contracts as contracts
from tv_quant.contracts.artifact_contract import dependency_hash
from tv_quant.contracts.capability_registry import (
    capability_snapshot_hash,
    load_capability_registry,
)
from tv_quant.contracts.confirmation import (
    ApprovalRecord,
)
from tv_quant.contracts.data_plan import build_data_plan
from tv_quant.contracts.execution_assumptions import (
    assumptions_hash,
    build_execution_assumptions,
)
from tv_quant.contracts.runner_protocol import RunnerMode, RunnerRequest, run_v2
from tv_quant.run_manifest import canonical_hash, sha256_file


_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / (
    "capability-registry-v2.1.json"
)
_PUBLIC_V22_TYPES = (
    "StrategySpecV2",
    "NormalizedStrategyIR",
    "DataPlan",
    "DatasetRequirement",
    "ExecutionAssumptions",
    "CapabilityRegistry",
    "ConfirmationRequest",
    "ConfirmationGrant",
    "RunnerRequest",
    "RunnerResponse",
    "DependencyFingerprint",
    "ProvisionalEvidence",
    "FormalResultContract",
    "TemplateLookupKey",
    "TemplateRecord",
)


def _phase1_payload() -> dict[str, object]:
    return {
        "strategy_name": "ema_baseline",
        "asset_class": "equity",
        "symbol": "SPY",
        "benchmark": "buy_and_hold",
        "timeframe": "1d",
        "start_date": "2020-01-01",
        "end_date": "2024-12-31",
        "initial_capital": 100000,
        "entry_rules": [
            {"type": "ema_crossover", "fast_period": 50, "slow_period": 200}
        ],
        "exit_rules": [{"type": "ema_crossunder"}],
        "position_sizing": {"type": "cash_limited_long_only"},
        "commission_model": {"type": "basis_points", "value": 5},
        "slippage_model": {"type": "basis_points", "value": 5},
        "fill_timing": "next_bar",
        "data_source": "validated_local_cache_first",
        "in_sample_period": None,
        "out_of_sample_period": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _public_type(name: str) -> type:
    assert name in contracts.__all__, f"missing public contract export: {name}"
    value = getattr(contracts, name, None)
    assert isinstance(value, type), f"public contract is not a type: {name}"
    return value


def _write_gate_configs(tmp_path: Path) -> tuple[Path, Path, Phase1ToV2AdapterResult]:
    config_root = tmp_path / "config"
    config_root.mkdir()
    phase1_path = config_root / "phase1.json"
    source = json.dumps(_phase1_payload(), sort_keys=True, indent=2) + "\n"
    phase1_path.write_text(source, encoding="utf-8")
    result = adapt_phase1_to_v2(phase1_path, "phase1-to-v2/1")
    v2_path = config_root / "strategy-v2.json"
    v2_path.write_text(
        json.dumps(_plain(result.v2_payload), sort_keys=True),
        encoding="utf-8",
    )
    return phase1_path, v2_path, result


def _evidence_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    from tv_quant.contracts import runner_protocol

    repository_root = tmp_path / "trusted-repository"
    root = repository_root / "reports" / "v2-runner-evidence"
    root.mkdir(parents=True)
    monkeypatch.setattr(
        runner_protocol,
        "_TRUSTED_REPOSITORY_ROOT",
        repository_root.resolve(),
    )
    return root


def _request(
    config_path: Path,
    mode: RunnerMode,
    evidence_root: Path,
    **changes: object,
) -> RunnerRequest:
    values: dict[str, object] = {
        "config_path": config_path,
        "mode": mode,
        "evidence_root": evidence_root,
    }
    values.update(changes)
    return RunnerRequest(**values)


def _prepare(config_path: Path, evidence_root: Path):
    response = run_v2(
        _request(config_path, RunnerMode.PREPARE_CONFIRMATION, evidence_root)
    )
    request_path = evidence_root / response.run_id / "confirmation-request.json"
    assert response.status == "SUCCESS", response.to_json()
    assert request_path.is_file()
    return response, request_path


def _approval_path(request_path: Path) -> Path:
    request_payload = json.loads(request_path.read_text(encoding="utf-8"))
    approval = ApprovalRecord(
        approval_id="approval-task17",
        confirmation_request_id=request_payload["confirmation_request_id"],
        decision="CONFIRMED_EXECUTE",
        recorded_at_utc=request_payload["generated_at"],
        actor="dialogue.user",
    )
    path = request_path.with_name("approval-record.json")
    path.write_text(json.dumps(asdict(approval), sort_keys=True), encoding="utf-8")
    return path


def _grant(config_path: Path, evidence_root: Path, request_path: Path):
    response = run_v2(
        _request(
            config_path,
            RunnerMode.GRANT_CONFIRMATION,
            evidence_root,
            confirmation_request_path=request_path,
            approval_record_path=_approval_path(request_path),
        )
    )
    assert response.status == "SUCCESS"
    assert response.confirmation_token
    return response


def _load_data_plan(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    requirement_type = _public_type("DatasetRequirement")
    plan_type = _public_type("DataPlan")
    primary = requirement_type(**payload["primary"])
    auxiliary = tuple(requirement_type(**item) for item in payload["auxiliary"])
    return plan_type(
        schema_version=payload["schema_version"],
        primary=primary,
        auxiliary=auxiliary,
        requested_range=payload["requested_range"],
        data_plan_hash=payload["data_plan_hash"],
    )


def _build_assumptions(ir, plan):
    registry = load_capability_registry(_REGISTRY_PATH)
    return build_execution_assumptions(
        ir,
        plan,
        {
            "cost_profile_id": plan.primary.cost_profile_requirement,
            "corporate_action_profile_id": "corporate-actions.v1",
            "benchmark_protocol_id": "buy-and-hold.v1",
            "benchmark_protocol_version": "v1",
            "capability_snapshot_hash": capability_snapshot_hash(registry),
            "normalizer_version": "v2.1",
        },
    )


def _provisional_evidence(response, request, assumptions):
    evidence_type = _public_type("ProvisionalEvidence")
    return evidence_type(
        run_id=response.run_id,
        evidence_kind="confirmation",
        paths=(
            f"{response.run_id}/confirmation-request.json",
            f"{response.run_id}/normalized-ir.json",
            f"{response.run_id}/data-plan.json",
        ),
        config_hash=request.normalized_config_hash,
        data_plan_hash=request.data_plan_hash,
        capability_snapshot_hash=assumptions.capability_snapshot_hash,
        status="PROVISIONAL",
        formal_result_published=False,
    )


def test_end_to_end_validate_prepare_grant_execute_stops_before_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Crossing the typed gate or reversing the adapter would permit execution."""
    phase1_path, v2_path, adapted = _write_gate_configs(tmp_path)
    evidence_root = _evidence_root(tmp_path, monkeypatch)
    source_bytes = phase1_path.read_bytes()

    assert adapted.v2_payload["data"]["legacy_costs"] == {
        "commission_bps": "5",
        "slippage_bps": "5",
    }
    validated = run_v2(_request(v2_path, RunnerMode.VALIDATE, evidence_root))
    prepared, request_path = _prepare(v2_path, evidence_root)
    plan = _load_data_plan(request_path.with_name("data-plan.json"))
    assumptions = _build_assumptions(adapted.normalized_ir, plan)
    request_type = _public_type("ConfirmationRequest")
    confirmation = request_type(
        **json.loads(request_path.read_text(encoding="utf-8"))
    )
    granted = _grant(v2_path, evidence_root, request_path)
    state = json.loads(
        request_path.with_name("confirmation-state.json").read_text(encoding="utf-8")
    )
    grant = _public_type("ConfirmationGrant")(**state["grant"])
    evidence = _provisional_evidence(prepared, confirmation, assumptions)
    token = granted.confirmation_token
    assert isinstance(token, str)
    execute_request = _request(
        v2_path,
        RunnerMode.EXECUTE,
        evidence_root,
        confirmation_request_path=request_path,
        confirmation_token=token,
    )
    executed = run_v2(execute_request)
    replayed = run_v2(execute_request)

    assert isinstance(adapted, Phase1ToV2AdapterResult)
    assert isinstance(adapted.strategy_spec_v2, _public_type("StrategySpecV2"))
    assert isinstance(adapted.normalized_ir, _public_type("NormalizedStrategyIR"))
    assert isinstance(plan, _public_type("DataPlan"))
    assert isinstance(assumptions, _public_type("ExecutionAssumptions"))
    assert isinstance(confirmation, _public_type("ConfirmationRequest"))
    assert isinstance(grant, _public_type("ConfirmationGrant"))
    assert all(
        isinstance(response, _public_type("RunnerResponse"))
        for response in (validated, prepared, granted, executed, replayed)
    )
    assert isinstance(evidence, _public_type("ProvisionalEvidence"))
    assert phase1_path.read_bytes() == source_bytes
    assert adapted.source_bytes_unchanged is True
    assert adapted.v2_payload["fill_timing"] == "next_bar_open"
    assert adapted.normalized_ir.fill_timing == assumptions.fill_timing
    assert confirmation.data_plan_hash == plan.data_plan_hash
    assert confirmation.assumptions_hash == assumptions_hash(assumptions)
    assert grant.bound_assumptions_hash == confirmation.assumptions_hash
    assert validated.status == prepared.status == granted.status == "SUCCESS"
    assert executed.status == "NOT_IMPLEMENTED"
    assert executed.blocker_code == "EXECUTION_CAPABILITY_NOT_IMPLEMENTED"
    assert executed.formal_result_published is False
    assert replayed.blocker_code == "CONFIRMATION_ALREADY_USED"


def test_blocker_prevents_data_backtest_formal_artifact_and_template(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine blocker must leave only grant evidence, never formal outputs."""
    _phase1_path, v2_path, _adapted = _write_gate_configs(tmp_path)
    evidence_root = _evidence_root(tmp_path, monkeypatch)
    _prepared, request_path = _prepare(v2_path, evidence_root)
    granted = _grant(v2_path, evidence_root, request_path)

    executed = run_v2(
        _request(
            v2_path,
            RunnerMode.EXECUTE,
            evidence_root,
            confirmation_request_path=request_path,
            confirmation_token=granted.confirmation_token,
        )
    )

    assert executed.status == "NOT_IMPLEMENTED"
    assert executed.blocker_code == "EXECUTION_CAPABILITY_NOT_IMPLEMENTED"
    assert executed.formal_result_published is False
    assert executed.run_directory is None
    assert executed.audit_status is None
    assert executed.report_summary_path is None
    assert sorted(path.name for path in request_path.parent.iterdir()) == [
        ".confirmation-state.json.lock",
        "approval-record.json",
        "confirmation-request.json",
        "confirmation-state.json",
        "data-plan.json",
        "normalized-ir.json",
    ]


def test_v21_runner_response_is_serializable_and_versioned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-compact or unversioned response would break runner consumers."""
    _phase1_path, v2_path, _adapted = _write_gate_configs(tmp_path)
    evidence_root = _evidence_root(tmp_path, monkeypatch)

    response = run_v2(_request(v2_path, RunnerMode.VALIDATE, evidence_root))
    serialized = response.to_json()
    payload = json.loads(serialized)

    assert isinstance(response, _public_type("RunnerResponse"))
    assert tuple(payload) == (
        "protocol_version",
        "status",
        "blocker_code",
        "run_id",
        "confirmation_request_id",
        "confirmation_token",
        "run_directory",
        "audit_status",
        "formal_result_published",
        "report_summary_path",
        "next_action",
    )
    assert payload["protocol_version"] == "v2.1"
    assert payload["formal_result_published"] is False
    assert serialized == json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert "\n" not in serialized


def test_v22_entry_interfaces_are_stable() -> None:
    """Removing a concrete V2.2 input type would break the next phase entry gate."""
    public_types = {name: _public_type(name) for name in _PUBLIC_V22_TYPES}

    assert tuple(mode.value for mode in contracts.RunnerMode) == (
        "validate",
        "prepare_confirmation",
        "grant_confirmation",
        "execute",
    )
    assert tuple(inspect.signature(contracts.run_v2).parameters) == ("request",)
    assert contracts.RunnerRequest is public_types["RunnerRequest"]
    assert contracts.RunnerResponse is public_types["RunnerResponse"]
    assert Phase1ToV2AdapterResult.__name__ == "Phase1ToV2AdapterResult"


def test_confirmation_token_is_returned_only_by_grant_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisting or replaying plaintext authority would violate one-time handoff."""
    _phase1_path, v2_path, _adapted = _write_gate_configs(tmp_path)
    evidence_root = _evidence_root(tmp_path, monkeypatch)
    validated = run_v2(_request(v2_path, RunnerMode.VALIDATE, evidence_root))
    prepared, request_path = _prepare(v2_path, evidence_root)
    granted = _grant(v2_path, evidence_root, request_path)
    token = granted.confirmation_token
    assert isinstance(token, str)
    execute_request = _request(
        v2_path,
        RunnerMode.EXECUTE,
        evidence_root,
        confirmation_request_path=request_path,
        confirmation_token=token,
    )
    executed = run_v2(execute_request)
    replayed = run_v2(execute_request)

    assert (
        validated.confirmation_token,
        prepared.confirmation_token,
        executed.confirmation_token,
        replayed.confirmation_token,
    ) == (None, None, None, None)
    assert granted.to_json().count(token) == 1
    assert all(
        token not in path.read_text(encoding="utf-8")
        for path in evidence_root.rglob("*.json")
    )
    persisted = json.loads(
        request_path.with_name("confirmation-state.json").read_text(encoding="utf-8")
    )
    assert "confirmation_token_hash" in persisted["grant"]
    assert "confirmation_token" not in persisted["grant"]
    assert replayed.blocker_code == "CONFIRMATION_ALREADY_USED"


def test_evidence_paths_are_contained_and_dependency_hash_is_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Traversal or an omitted dependency field would make evidence unauditable."""
    phase1_path, v2_path, adapted = _write_gate_configs(tmp_path)
    evidence_root = _evidence_root(tmp_path, monkeypatch)
    prepared, request_path = _prepare(v2_path, evidence_root)
    plan = _load_data_plan(request_path.with_name("data-plan.json"))
    assumptions = _build_assumptions(adapted.normalized_ir, plan)
    confirmation = _public_type("ConfirmationRequest")(
        **json.loads(request_path.read_text(encoding="utf-8"))
    )
    evidence = _provisional_evidence(prepared, confirmation, assumptions)

    resolved = evidence.resolved_paths(evidence_root)
    assert all(path.is_file() for path in resolved)
    assert all(path.relative_to(evidence_root) for path in resolved)
    assert evidence.formal_result_published is False

    fingerprint_type = _public_type("DependencyFingerprint")
    fingerprint = fingerprint_type(
        schema_version="v2.1",
        validator_version="v2.1",
        normalizer_version="v2.1",
        compiler_version="v2.1",
        capability_snapshot_hash=assumptions.capability_snapshot_hash,
        status_registry_hash=sha256_file(
            Path(__file__).resolve().parents[2]
            / "src"
            / "tv_quant"
            / "contracts"
            / "status_codes.py"
        ),
        cost_profile_id=assumptions.cost_profile_id,
        cost_profile_hash=hashlib.sha256(v2_path.read_bytes()).hexdigest(),
        corporate_action_profile_id=assumptions.corporate_action_profile_id,
        corporate_action_profile_hash=hashlib.sha256(
            phase1_path.read_bytes()
        ).hexdigest(),
        benchmark_protocol_version=assumptions.benchmark_protocol_version,
        engine_id="NOT_IMPLEMENTED",
        engine_version="NOT_IMPLEMENTED",
        data_contract_version="v2.1",
        plugin_name=None,
        plugin_version=None,
        plugin_hash=None,
    )
    digest = dependency_hash(fingerprint)
    mutations = {
        "validator_version": "v2.1.1",
        "normalizer_version": "v2.1.1",
        "compiler_version": "v2.1.1",
        "capability_snapshot_hash": "a" * 64,
        "status_registry_hash": "b" * 64,
        "cost_profile_id": "cost-profile.v2",
        "cost_profile_hash": "c" * 64,
        "corporate_action_profile_id": "corporate-actions.v2",
        "corporate_action_profile_hash": "d" * 64,
        "benchmark_protocol_version": "v2",
        "data_contract_version": "v2.1.1",
    }

    assert set(asdict(fingerprint)) == {
        "schema_version",
        "validator_version",
        "normalizer_version",
        "compiler_version",
        "capability_snapshot_hash",
        "status_registry_hash",
        "cost_profile_id",
        "cost_profile_hash",
        "corporate_action_profile_id",
        "corporate_action_profile_hash",
        "benchmark_protocol_version",
        "engine_id",
        "engine_version",
        "data_contract_version",
        "plugin_name",
        "plugin_version",
        "plugin_hash",
    }
    assert len(digest) == 64
    assert all(
        dependency_hash(replace(fingerprint, **{field: value})) != digest
        for field, value in mutations.items()
    )
    assert canonical_hash(asdict(fingerprint)) == digest
