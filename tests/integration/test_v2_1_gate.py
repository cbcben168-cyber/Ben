"""End-to-end checks for the public V2.1 contract gate."""

from __future__ import annotations

import ast
from collections.abc import Mapping
from dataclasses import asdict, replace
import hashlib
import inspect
import json
from pathlib import Path
import re

import pytest

from tv_quant.adapters.phase1_config_adapter import (
    Phase1ToV2AdapterResult,
    adapt_phase1_to_v2,
)
import tv_quant.adapters.phase1_config_adapter as phase1_adapter
import tv_quant.contracts as contracts
import tv_quant.contracts.artifact_contract as artifact_contract
from tv_quant.contracts.artifact_contract import dependency_hash
from tv_quant.contracts.capability_registry import (
    capability_snapshot_hash,
    load_capability_registry,
)
from tv_quant.contracts.confirmation import (
    ApprovalRecord,
)
import tv_quant.contracts.confirmation as confirmation_contract
from tv_quant.contracts.data_plan import build_data_plan
from tv_quant.contracts.execution_assumptions import (
    assumptions_hash,
    build_execution_assumptions,
)
import tv_quant.contracts.status_codes as status_codes
from tv_quant.run_manifest import canonical_hash, sha256_file


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_REGISTRY_PATH = _REPOSITORY_ROOT / "config" / (
    "capability-registry-v2.1.json"
)
_PLAN_PATH = _REPOSITORY_ROOT / "docs" / "superpowers" / "plans" / (
    "2026-07-27-v2-1-contract-gate-implementation-plan.md"
)
_DESIGN_PATH = _REPOSITORY_ROOT / "docs" / "superpowers" / "specs" / (
    "2026-07-26-quant-research-automation-v2-design.md"
)
def _section(document: str, heading: str) -> str:
    assert heading in document, f"missing acceptance section: {heading}"
    start = document.index(heading) + len(heading)
    remainder = document[start:]
    heading_level = len(heading) - len(heading.lstrip("#"))
    next_heading = re.search(rf"\n#{{1,{heading_level}}} ", remainder)
    return remainder if next_heading is None else remainder[: next_heading.start()]


def _table_rows(section: str) -> list[list[str]]:
    return [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|") and not line.startswith("|---")
    ][1:]


def _fenced_lines(section: str) -> tuple[str, ...]:
    block = section.split("~~~text", 1)[1].split("~~~", 1)[0]
    return tuple(line.strip() for line in block.splitlines() if line.strip())


def _evidence_refs(cell: str) -> tuple[str, ...]:
    return tuple(re.findall(r"`([^`]+)`", cell))


def _assert_test_reference_exists(reference: str) -> None:
    if not reference.startswith("tests/"):
        return
    path_text, separator, function_name = reference.partition("::")
    path = _REPOSITORY_ROOT / path_text
    assert path.is_file(), f"missing evidence path: {path_text}"
    if not separator:
        return
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=path_text)
    functions = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert function_name in functions, f"missing evidence function: {reference}"


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
    mode: contracts.RunnerMode,
    evidence_root: Path,
    **changes: object,
) -> contracts.RunnerRequest:
    values: dict[str, object] = {
        "config_path": config_path,
        "mode": mode,
        "evidence_root": evidence_root,
    }
    values.update(changes)
    return contracts.RunnerRequest(**values)


def _prepare(config_path: Path, evidence_root: Path):
    response = contracts.run_v2(
        _request(
            config_path,
            contracts.RunnerMode.PREPARE_CONFIRMATION,
            evidence_root,
        )
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


def _grant_request(config_path: Path, evidence_root: Path, request_path: Path):
    return contracts.run_v2(
        _request(
            config_path,
            contracts.RunnerMode.GRANT_CONFIRMATION,
            evidence_root,
            confirmation_request_path=request_path,
            approval_record_path=_approval_path(request_path),
        )
    )


def _grant(config_path: Path, evidence_root: Path, request_path: Path):
    response = _grant_request(config_path, evidence_root, request_path)
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


def _provisional_evidence(granted, grant, executed, assumptions):
    evidence_type = _public_type("ProvisionalEvidence")
    return evidence_type(
        run_id=granted.run_id,
        evidence_kind="execution-blocker",
        paths=(
            f"{granted.run_id}/confirmation-request.json",
            f"{granted.run_id}/normalized-ir.json",
            f"{granted.run_id}/data-plan.json",
        ),
        config_hash=grant.bound_config_hash,
        data_plan_hash=grant.bound_data_plan_hash,
        capability_snapshot_hash=assumptions.capability_snapshot_hash,
        status=executed.status,
        formal_result_published=executed.formal_result_published,
    )


def test_end_to_end_validate_prepare_grant_execute_stops_before_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Internal runner calls or broken grant/response/evidence bindings must fail."""
    phase1_path, v2_path, adapted = _write_gate_configs(tmp_path)
    evidence_root = _evidence_root(tmp_path, monkeypatch)
    source_bytes = phase1_path.read_bytes()

    assert adapted.v2_payload["data"]["legacy_costs"] == {
        "commission_bps": "5",
        "slippage_bps": "5",
    }
    validated = contracts.run_v2(
        _request(v2_path, contracts.RunnerMode.VALIDATE, evidence_root)
    )
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
    token = granted.confirmation_token
    assert isinstance(token, str)
    execute_request = _request(
        v2_path,
        contracts.RunnerMode.EXECUTE,
        evidence_root,
        confirmation_request_path=request_path,
        confirmation_token=token,
    )
    executed = contracts.run_v2(execute_request)
    replayed = contracts.run_v2(execute_request)
    evidence = _provisional_evidence(granted, grant, executed, assumptions)

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
    assert (
        confirmation.confirmation_request_id
        == grant.confirmation_request_id
        == granted.confirmation_request_id
        == executed.confirmation_request_id
    )
    assert evidence.run_id == granted.run_id == executed.run_id
    assert evidence.config_hash == grant.bound_config_hash
    assert grant.bound_config_hash == confirmation.normalized_config_hash
    assert evidence.data_plan_hash == grant.bound_data_plan_hash
    assert grant.bound_data_plan_hash == confirmation.data_plan_hash
    assert evidence.status == executed.status
    assert evidence.formal_result_published is executed.formal_result_published
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

    executed = contracts.run_v2(
        _request(
            v2_path,
            contracts.RunnerMode.EXECUTE,
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

    response = contracts.run_v2(
        _request(v2_path, contracts.RunnerMode.VALIDATE, evidence_root)
    )
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


def test_final_plan_review_matrix_has_p1_through_p15_resolved() -> None:
    """An omitted review resolution or task assignment would reopen the plan."""
    plan = _PLAN_PATH.read_text(encoding="utf-8")
    matrix = {
        row[0]: row
        for row in _table_rows(_section(plan, "## Final Plan Review Resolution Matrix"))
    }
    expected = {
        "P1": ("BLOCKER", (4, 6, 7, 18, 19), "Phase1ToV2Adapter"),
        "P2": ("BLOCKER", (3, 4, 6), "根级显式必填"),
        "P3": ("HIGH", (3, 4, 6), "position_sizing"),
        "P4": ("BLOCKER", (5, 6), "PredicateExpression"),
        "P5": ("BLOCKER", (9, 11, 12, 18), "ExecutionAssumptions"),
        "P6": ("BLOCKER", (11, 12, 15, 18), "confirmation_token"),
        "P7": ("HIGH", (2, 3, 5, 6, 18), "唯一事实来源"),
        "P8": ("BLOCKER", (3, 7, 10, 18), "not_live_verified"),
        "P9": ("HIGH", (2, 6), "canonical decimal string"),
        "P10": ("BLOCKER", (12, 18), "msvcrt"),
        "P11": ("HIGH", (13, 18), "resolve_under_root"),
        "P12": ("HIGH", (13, 14, 17, 18), "dependency_hash"),
        "P13": ("HIGH", (16, 17, 18), "one active version"),
        "P14": ("HIGH", (10, 18), "formal eligibility"),
        "P15": ("HIGH", (1, 18), "user_action"),
    }
    expected_evidence = {
        "P1": (
            "tests/adapters/test_phase1_config_adapter.py::test_phase1_to_v2_result_preserves_source_and_generated_hashes",
            "tests/adapters/test_phase1_config_adapter.py::test_v2_to_phase1_adapter_is_not_part_of_v21",
        ),
        "P2": (
            "tests/contracts/test_strategy_v2_schema.py::test_each_explicit_root_field_is_required_without_normalization_default",
            "tests/contracts/test_normalized_ir.py::test_missing_explicit_fields_never_become_normalization_defaults",
        ),
        "P3": (
            "tests/contracts/test_strategy_v2_schema.py::test_disabled_stop_target_and_empty_filters_must_be_present",
            "tests/contracts/test_normalized_ir.py::test_normalization_requires_position_sizing",
        ),
        "P4": (
            "tests/contracts/test_ast_contract.py::test_entry_exit_and_filter_roots_require_predicates",
            "tests/contracts/test_ast_contract.py::test_node_id_depth_and_node_count_limits_are_deterministic",
        ),
        "P5": (
            "tests/contracts/test_execution_assumptions.py::test_assumptions_hash_accepts_only_execution_assumptions",
            "tests/contracts/test_confirmation.py::test_request_binds_formal_execution_assumptions_hash",
        ),
        "P6": (
            "tests/contracts/test_runner_protocol.py::test_grant_confirmation_returns_token_once",
            "tests/contracts/test_runner_protocol.py::test_non_grant_modes_never_return_plaintext_token",
        ),
        "P7": (
            "tests/contracts/test_schema_contract.py::test_python_contract_definitions_are_unique_source_of_truth",
            "tests/contracts/test_strategy_v2_schema.py::test_python_contract_and_json_schema_required_fields_match",
        ),
        "P8": (
            "tests/contracts/test_strategy_v2_schema.py::test_symbol_schema_accepts_valid_us_equity_symbol_without_spy_qqq_cap",
            "tests/contracts/test_capability_registry.py::test_require_formal_rejects_not_live_verified",
        ),
        "P9": (
            "tests/contracts/test_numeric_canonicalization.py::test_decimal_strings_normalize_1_1_00_to_one_semantic_hash",
            "tests/contracts/test_normalized_ir.py::test_decimal_numeric_forms_produce_identical_hash",
        ),
        "P10": (
            "tests/contracts/test_confirmation_store.py::test_atomic_consume_allows_exactly_one_consumer",
            "tests/contracts/test_confirmation_store.py::test_windows_lock_backend_uses_msvcrt_contract",
            "tests/contracts/test_confirmation_store.py::test_posix_lock_backend_uses_fcntl_contract",
            "tests/contracts/test_confirmation_store.py::test_crash_before_replace_leaves_grant_retryable",
        ),
        "P11": (
            "tests/contracts/test_path_safety.py::test_resolve_under_root_rejects_parent_traversal_absolute_and_root_escape",
            "tests/contracts/test_path_safety.py::test_resolve_under_root_rejects_ntfs_ads_and_reserved_dos_devices",
        ),
        "P12": (
            "tests/contracts/test_artifact_contract.py::test_dependency_hash_payload_contains_all_components",
            "tests/integration/test_v2_1_gate.py::test_evidence_paths_are_contained_and_dependency_hash_is_complete",
        ),
        "P13": (
            "tests/contracts/test_template_contract.py::test_only_one_active_version_exists_per_key",
            "tests/contracts/test_template_contract.py::test_supersedes_points_to_same_key_older_record",
            "tests/contracts/test_template_contract.py::test_supersedes_cycles_and_non_monotonic_versions_are_rejected",
        ),
        "P14": (
            "tests/contracts/test_capability_registry.py::test_symbol_structural_support_is_not_phase1_execution_support",
            "tests/contracts/test_capability_registry.py::test_require_formal_rejects_not_live_verified",
        ),
        "P15": (
            "tests/contracts/test_status_codes.py::test_recoverable_retryable_terminal_semantics_are_consistent",
            "tests/integration/test_v2_1_security.py::test_all_status_metadata_defines_recoverable_retryable_terminal",
        ),
    }
    design_rows = _table_rows(
        _section(
            _DESIGN_PATH.read_text(encoding="utf-8"),
            "### 29.2 Final plan review evidence",
        )
    )

    assert tuple(matrix) == tuple(expected)
    for review_id, (severity, task_numbers, resolution_fragment) in expected.items():
        row = matrix[review_id]
        assert row[1] == severity
        assert resolution_fragment in row[2]
        assert tuple(int(value) for value in re.findall(r"\d+", row[3])) == task_numbers
        assert row[4]
    assert {row[0]: row[2] for row in design_rows} == {
        review_id: "RESOLVED" for review_id in expected
    }
    actual_evidence = {row[0]: _evidence_refs(row[1]) for row in design_rows}
    assert actual_evidence == expected_evidence
    for references in actual_evidence.values():
        for reference in references:
            _assert_test_reference_exists(reference)


def test_v21_exit_gate_checklist_is_complete() -> None:
    """Missing exit evidence or acceptance commands must keep V2.1 unaccepted."""
    design = _DESIGN_PATH.read_text(encoding="utf-8")
    exit_rows = _table_rows(_section(design, "### 29.3 V2.1 exit evidence"))
    expected_ids = tuple(f"E{index}" for index in range(1, 26))
    expected_condition_fragments = (
        "Schema identity",
        "StrategySpecV2 valid load",
        "Explicit required root fields",
        "Typed AST root",
        "NormalizedStrategyIR",
        "Stable normalized hash",
        "Phase1ToV2Adapter",
        "ExecutionAssumptions",
        "ConfirmationRequest",
        "ConfirmationGrant",
        "Plaintext token",
        "Missing, invalid, expired, mismatched, and reused tokens",
        "Capability status",
        "Artifact ownership",
        "Provisional and formal results",
        "Four runner modes",
        "Explicit V2 CLI namespace",
        "Template contract",
        "Template registry",
        "Contract, adapter, CLI, and integration suites",
        "Existing Phase 1 suite",
        "Static review",
        "Acceptance performed no download",
        "Every status defines",
        "Final Task 19 tracked tree",
    )
    expected_evidence = {
        "E1": (
            "tests/contracts/test_schema_contract.py::test_python_contract_definitions_are_unique_source_of_truth",
            "tests/contracts/test_strategy_v2_schema.py::test_schema_id_and_version_are_quant_strategy_v2_v21",
        ),
        "E2": (
            "tests/contracts/test_strategy_v2_schema.py::test_valid_minimal_v2_config_loads",
            "tests/contracts/test_strategy_v2_schema.py::test_invalid_enum_and_unknown_field_are_rejected",
            "tests/contracts/test_strategy_v2_schema.py::test_legacy_phase1_mapping_requires_explicit_v2_loader",
        ),
        "E3": (
            "tests/contracts/test_strategy_v2_schema.py::test_each_explicit_root_field_is_required_without_normalization_default",
            "tests/contracts/test_normalized_ir.py::test_missing_explicit_fields_never_become_normalization_defaults",
        ),
        "E4": (
            "tests/contracts/test_ast_contract.py::test_entry_exit_and_filter_roots_require_predicates",
            "tests/contracts/test_ast_contract.py::test_node_id_depth_and_node_count_limits_are_deterministic",
        ),
        "E5": (
            "tests/contracts/test_normalized_ir.py::test_identical_semantics_produce_identical_ir_and_hash",
            "tests/contracts/test_normalized_ir.py::test_ir_contains_no_float_callable_or_python_source",
        ),
        "E6": (
            "tests/contracts/test_normalized_ir.py::test_decimal_numeric_forms_produce_identical_hash",
            "tests/integration/test_v2_1_security.py::test_v2_contracts_reference_existing_hash_owner",
        ),
        "E7": (
            "tests/adapters/test_phase1_config_adapter.py::test_phase1_to_v2_result_preserves_source_and_generated_hashes",
            "tests/adapters/test_phase1_config_adapter.py::test_v2_to_phase1_adapter_is_not_part_of_v21",
        ),
        "E8": (
            "tests/contracts/test_execution_assumptions.py::test_assumptions_contains_all_frozen_policy_and_version_fields",
            "tests/contracts/test_execution_assumptions.py::test_assumptions_hash_accepts_only_execution_assumptions",
        ),
        "E9": (
            "tests/contracts/test_confirmation.py::test_request_contains_three_binding_hashes_and_summaries",
            "tests/contracts/test_confirmation.py::test_request_hashes_change_with_each_bound_contract",
        ),
        "E10": (
            "tests/contracts/test_confirmation_store.py::test_atomic_consume_allows_exactly_one_consumer",
            "tests/contracts/test_confirmation_store.py::test_windows_lock_backend_uses_msvcrt_contract",
            "tests/contracts/test_confirmation_store.py::test_posix_lock_backend_uses_fcntl_contract",
            "tests/contracts/test_confirmation_store.py::test_crash_before_replace_leaves_grant_retryable",
        ),
        "E11": (
            "tests/integration/test_v2_1_gate.py::test_confirmation_token_is_returned_only_by_grant_response",
            "tests/integration/test_v2_1_security.py::test_plaintext_confirmation_token_is_absent_from_persistent_outputs",
        ),
        "E12": (
            "tests/contracts/test_confirmation_store.py::test_missing_expired_mismatched_and_reused_token_are_rejected",
            "tests/contracts/test_runner_protocol.py::test_execute_without_token_returns_confirmation_required",
            "tests/contracts/test_runner_protocol.py::test_execute_with_invalid_token_returns_confirmation_invalid",
        ),
        "E13": (
            "tests/contracts/test_capability_registry.py::test_symbol_structural_support_is_not_phase1_execution_support",
            "tests/contracts/test_capability_registry.py::test_require_formal_rejects_not_live_verified",
        ),
        "E14": (
            "tests/contracts/test_artifact_contract.py::test_existing_run_manifest_hash_owner_is_declared",
            "tests/integration/test_v2_1_security.py::test_v2_contracts_reference_existing_hash_owner",
        ),
        "E15": (
            "tests/contracts/test_artifact_contract.py::test_provisional_evidence_accepts_only_contained_paths",
            "tests/contracts/test_artifact_contract.py::test_v21_execute_cannot_mark_formal_result_published",
        ),
        "E16": (
            "tests/contracts/test_runner_protocol.py::test_runner_response_contains_required_short_json_fields",
            "tests/contracts/test_runner_protocol.py::test_execute_with_valid_token_consumes_once_and_returns_not_implemented",
        ),
        "E17": (
            "tests/pipeline/test_v2_cli_gate.py::test_v2_command_never_calls_legacy_run_pipeline_or_refresh",
            "tests/integration/test_v2_1_security.py::test_v2_runner_does_not_call_legacy_pipeline",
        ),
        "E18": (
            "tests/contracts/test_template_contract.py::test_template_record_contains_immutable_version_and_hashes",
            "tests/contracts/test_template_contract.py::test_invalidated_record_cannot_be_active",
        ),
        "E19": (
            "tests/contracts/test_template_contract.py::test_lookup_uses_key_not_file_mtime",
            "tests/contracts/test_template_contract.py::test_only_one_active_version_exists_per_key",
            "tests/contracts/test_template_contract.py::test_supersedes_cycles_and_non_monotonic_versions_are_rejected",
        ),
        "E20": (
            "tests/integration/test_v2_1_gate.py::test_final_plan_review_matrix_has_p1_through_p15_resolved",
            "tests/integration/test_v2_1_gate.py::test_v21_exit_gate_checklist_is_complete",
            "tests/integration/test_v2_1_gate.py::test_v22_entry_interfaces_match_public_exports",
        ),
        "E21": (
            "tests/integration/test_v2_1_security.py::test_phase1_suite_remains_unchanged",
        ),
        "E22": (
            "tests/integration/test_v2_1_security.py::test_v2_modules_have_no_network_provider_or_engine_import",
            "tests/integration/test_v2_1_security.py::test_v2_modules_have_no_arbitrary_execution_construct",
        ),
        "E23": (
            "tests/contracts/test_runner_protocol.py::test_runner_does_not_call_pipeline_backtest_or_provider",
            "tests/contracts/test_confirmation_store.py::test_store_has_no_network_process_or_backtest_side_effects",
        ),
        "E24": (
            "tests/contracts/test_status_codes.py::test_recoverable_retryable_terminal_semantics_are_consistent",
            "tests/integration/test_v2_1_security.py::test_all_status_metadata_defines_recoverable_retryable_terminal",
        ),
        "E25": ("git status --short",),
    }
    required_commands = (
        "python -m pytest tests/contracts tests/adapters "
        "tests/pipeline/test_v2_cli_gate.py tests/integration -q",
        "python -m pytest tests/contracts -q",
        "python -m pytest tests/adapters -q",
        "python -m pytest tests/pipeline/test_v2_cli_gate.py -q",
        "python -m pytest tests/integration -q",
        "python -m pytest tests/pipeline -q",
        "python -m pytest tests -q",
        "python -m compileall -q src tests",
        "git diff --check",
    )

    assert tuple(row[0] for row in exit_rows) == expected_ids
    assert all(
        fragment in row[1]
        for fragment, row in zip(expected_condition_fragments, exit_rows, strict=True)
    )
    actual_evidence = {row[0]: _evidence_refs(row[2]) for row in exit_rows}
    assert actual_evidence == expected_evidence
    assert exit_rows[-1][2] == "Task 19 post-commit `git status --short` review"
    assert all(row[3] == "PASS" for row in exit_rows)
    for references in actual_evidence.values():
        for reference in references:
            _assert_test_reference_exists(reference)
    assert all(command in design for command in required_commands)
    assert "V2.1_CONTRACT_GATE_ACCEPTED" in design
    assert "570c518ed1429d3b84f6fe9151bd18ea621f1150" in design
    assert "36ac03d7" in design


def test_v22_entry_interfaces_match_public_exports() -> None:
    """Documented V2.2 inputs must be concrete, independently exported types."""
    plan_interfaces = _fenced_lines(
        _section(
            _PLAN_PATH.read_text(encoding="utf-8"),
            "## 22. V2.2 Entry Gate",
        )
    )
    design_rows = _table_rows(
        _section(
            _DESIGN_PATH.read_text(encoding="utf-8"),
            "### 29.4 V2.2 frozen public interfaces",
        )
    )
    expected_mappings = {
        "StrategySpecV2": ("tv_quant.contracts", ("StrategySpecV2",)),
        "NormalizedStrategyIR": ("tv_quant.contracts", ("NormalizedStrategyIR",)),
        "DataPlan": ("tv_quant.contracts", ("DataPlan",)),
        "DatasetRequirement": ("tv_quant.contracts", ("DatasetRequirement",)),
        "ExecutionAssumptions": ("tv_quant.contracts", ("ExecutionAssumptions",)),
        "CapabilityRegistry": ("tv_quant.contracts", ("CapabilityRegistry",)),
        "ConfirmationRequest": ("tv_quant.contracts", ("ConfirmationRequest",)),
        "ConfirmationGrant": ("tv_quant.contracts", ("ConfirmationGrant",)),
        "AuthorizedExecutionContext": (
            "tv_quant.contracts.confirmation",
            ("ConfirmationAuditRecord", "validate_and_consume"),
        ),
        "RunnerRequest": ("tv_quant.contracts", ("RunnerRequest",)),
        "RunnerResponse": ("tv_quant.contracts", ("RunnerResponse",)),
        "ArtifactContract": (
            "tv_quant.contracts.artifact_contract",
            (
                "ARTIFACT_OWNERS",
                "ArtifactOwner",
                "DependencyFingerprint",
                "ProvisionalEvidence",
                "FormalResultContract",
                "dependency_hash",
                "formal_eligibility",
            ),
        ),
        "DependencyFingerprint": ("tv_quant.contracts", ("DependencyFingerprint",)),
        "ProvisionalEvidence": ("tv_quant.contracts", ("ProvisionalEvidence",)),
        "FormalResultContract": ("tv_quant.contracts", ("FormalResultContract",)),
        "StatusCodeRegistry": (
            "tv_quant.contracts.status_codes",
            (
                "BlockerCode",
                "PipelineStatus",
                "StatusDefinition",
                "STATUS_DEFINITIONS",
                "status_definition",
                "status_snapshot_hash",
            ),
        ),
        "Phase1ToV2AdapterResult": (
            "tv_quant.adapters.phase1_config_adapter",
            ("Phase1ToV2AdapterResult",),
        ),
        "TemplateLookupKey": ("tv_quant.contracts", ("TemplateLookupKey",)),
        "TemplateRecord": ("tv_quant.contracts", ("TemplateRecord",)),
    }
    modules = {
        "tv_quant.contracts": contracts,
        "tv_quant.contracts.confirmation": confirmation_contract,
        "tv_quant.contracts.artifact_contract": artifact_contract,
        "tv_quant.contracts.status_codes": status_codes,
        "tv_quant.adapters.phase1_config_adapter": phase1_adapter,
    }
    documented_mappings = {
        row[0]: (row[1].strip("`"), _evidence_refs(row[2])) for row in design_rows
    }

    assert plan_interfaces == tuple(expected_mappings)
    assert tuple(documented_mappings) == plan_interfaces
    assert documented_mappings == expected_mappings
    for module_name, symbols in documented_mappings.values():
        module = modules[module_name]
        for symbol in symbols:
            assert hasattr(
                module, symbol
            ), f"missing concrete interface: {module_name}.{symbol}"
            if hasattr(module, "__all__"):
                assert symbol in module.__all__
    for frozen_name, (module_name, symbols) in documented_mappings.items():
        if frozen_name not in {
            "AuthorizedExecutionContext",
            "ArtifactContract",
            "StatusCodeRegistry",
        }:
            assert len(symbols) == 1
            assert isinstance(getattr(modules[module_name], symbols[0]), type)
    assert isinstance(confirmation_contract.ConfirmationAuditRecord, type)
    assert callable(confirmation_contract.validate_and_consume)
    assert isinstance(artifact_contract.ARTIFACT_OWNERS, tuple)
    assert isinstance(artifact_contract.ArtifactOwner, type)
    assert isinstance(artifact_contract.DependencyFingerprint, type)
    assert isinstance(artifact_contract.ProvisionalEvidence, type)
    assert isinstance(artifact_contract.FormalResultContract, type)
    assert callable(artifact_contract.dependency_hash)
    assert callable(artifact_contract.formal_eligibility)
    assert isinstance(status_codes.BlockerCode, type)
    assert isinstance(status_codes.PipelineStatus, type)
    assert isinstance(status_codes.StatusDefinition, type)
    assert isinstance(status_codes.STATUS_DEFINITIONS, tuple)
    assert callable(status_codes.status_definition)
    assert callable(status_codes.status_snapshot_hash)
    assert tuple(mode.value for mode in contracts.RunnerMode) == (
        "validate",
        "prepare_confirmation",
        "grant_confirmation",
        "execute",
    )
    assert tuple(inspect.signature(contracts.run_v2).parameters) == ("request",)


def test_confirmation_token_is_returned_only_by_grant_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second grant or any later response returning plaintext must fail."""
    _phase1_path, v2_path, _adapted = _write_gate_configs(tmp_path)
    evidence_root = _evidence_root(tmp_path, monkeypatch)
    validated = contracts.run_v2(
        _request(v2_path, contracts.RunnerMode.VALIDATE, evidence_root)
    )
    prepared, request_path = _prepare(v2_path, evidence_root)
    granted = _grant(v2_path, evidence_root, request_path)
    grant_replayed = _grant_request(v2_path, evidence_root, request_path)
    token = granted.confirmation_token
    assert isinstance(token, str)
    execute_request = _request(
        v2_path,
        contracts.RunnerMode.EXECUTE,
        evidence_root,
        confirmation_request_path=request_path,
        confirmation_token=token,
    )
    executed = contracts.run_v2(execute_request)
    replayed = contracts.run_v2(execute_request)

    assert (
        validated.confirmation_token,
        prepared.confirmation_token,
        grant_replayed.confirmation_token,
        executed.confirmation_token,
        replayed.confirmation_token,
    ) == (None, None, None, None, None)
    assert granted.to_json().count(token) == 1
    assert grant_replayed.status == "BLOCKED"
    assert grant_replayed.confirmation_token is None
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
    _prepared, request_path = _prepare(v2_path, evidence_root)
    plan = _load_data_plan(request_path.with_name("data-plan.json"))
    assumptions = _build_assumptions(adapted.normalized_ir, plan)
    confirmation = _public_type("ConfirmationRequest")(
        **json.loads(request_path.read_text(encoding="utf-8"))
    )
    granted = _grant(v2_path, evidence_root, request_path)
    grant_state = json.loads(
        request_path.with_name("confirmation-state.json").read_text(encoding="utf-8")
    )
    grant = _public_type("ConfirmationGrant")(**grant_state["grant"])
    executed = contracts.run_v2(
        _request(
            v2_path,
            contracts.RunnerMode.EXECUTE,
            evidence_root,
            confirmation_request_path=request_path,
            confirmation_token=granted.confirmation_token,
        )
    )
    evidence = _provisional_evidence(granted, grant, executed, assumptions)

    resolved = evidence.resolved_paths(evidence_root)
    assert all(path.is_file() for path in resolved)
    assert all(path.relative_to(evidence_root) for path in resolved)
    assert evidence.formal_result_published is False
    assert confirmation.confirmation_request_id == grant.confirmation_request_id
    assert executed.confirmation_request_id == grant.confirmation_request_id

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
