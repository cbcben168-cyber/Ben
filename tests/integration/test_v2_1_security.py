"""Static and runtime isolation checks for the V2.1 contract gate."""

from __future__ import annotations

import ast
import builtins
from collections.abc import Mapping
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import types

import pytest

from tv_quant.adapters.phase1_config_adapter import adapt_phase1_to_v2
from tv_quant.contracts.artifact_contract import ARTIFACT_OWNERS
from tv_quant.contracts.confirmation import ApprovalRecord
from tv_quant.contracts.status_codes import (
    BlockerCode,
    STATUS_DEFINITIONS,
    status_definition,
)
import tv_quant.run_manifest as hash_owner


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_V2_SOURCE_ROOTS = (
    _REPOSITORY_ROOT / "src" / "tv_quant" / "contracts",
    _REPOSITORY_ROOT / "src" / "tv_quant" / "adapters",
)
_HASH_PRIMITIVES = {
    "bind_artifact_hashes",
    "canonical_hash",
    "sha256_bytes",
    "sha256_file",
}
_PHASE1_TEST_FILES = (
    "tests/pipeline/helpers.py",
    "tests/pipeline/test_backtest_audit.py",
    "tests/pipeline/test_capabilities.py",
    "tests/pipeline/test_ema_acceptance.py",
    "tests/pipeline/test_pipeline_cli.py",
    "tests/pipeline/test_research_pipeline.py",
    "tests/pipeline/test_run_manifest.py",
    "tests/pipeline/test_run_pipeline_script.py",
    "tests/pipeline/test_strategy_spec.py",
    "tests/skills/test_agents_entry.py",
    "tests/skills/test_skill_contracts.py",
    "tests/skills/test_strategy_spec_skill.py",
    "tests/test_cli_futu.py",
    "tests/test_data_quality.py",
    "tests/test_futu_downloader.py",
    "tests/test_futu_quota.py",
    "tests/test_metrics.py",
    "tests/test_strategy.py",
)
_POST_PHASE1_TESTS = {
    "tests/pipeline/test_run_manifest.py::test_sha256_bytes_matches_known_digest",
    "tests/pipeline/test_run_manifest.py::test_existing_manifest_hash_functions_keep_behavior",
}
_PHASE1_TEST_COUNT = 106
_PHASE1_TEST_AST_SHA256 = (
    "793770e7333d88be9bc2912a5cae3e0f394fe96e4caa629225a8307d20124a75"
)


def _v2_sources() -> tuple[Path, ...]:
    return tuple(
        sorted(path for root in _V2_SOURCE_ROOTS for path in root.glob("*.py"))
    )


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(_REPOSITORY_ROOT / "src").with_suffix("").parts)


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _write_v2_config(tmp_path: Path) -> Path:
    phase1_path = _REPOSITORY_ROOT / "config" / "strategies" / "ema_baseline.yaml"
    adapted = adapt_phase1_to_v2(phase1_path, "phase1-to-v2/1")
    path = tmp_path / "strategy-v2.json"
    path.write_text(
        json.dumps(_plain(adapted.v2_payload), sort_keys=True),
        encoding="utf-8",
    )
    return path


def _evidence_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    runner: types.ModuleType,
) -> Path:
    repository_root = tmp_path / "trusted-repository"
    root = repository_root / "reports" / "v2-runner-evidence"
    root.mkdir(parents=True)
    monkeypatch.setattr(
        runner,
        "_TRUSTED_REPOSITORY_ROOT",
        repository_root.resolve(),
    )
    return root


def _request(
    runner: types.ModuleType,
    config_path: Path,
    mode: object,
    evidence_root: Path,
    **changes: object,
) -> object:
    values = {
        "config_path": config_path,
        "mode": mode,
        "evidence_root": evidence_root,
    }
    values.update(changes)
    return runner.RunnerRequest(**values)


def _prepare(
    runner: types.ModuleType,
    config_path: Path,
    evidence_root: Path,
) -> tuple[object, Path]:
    response = runner.run_v2(
        _request(
            runner,
            config_path,
            runner.RunnerMode.PREPARE_CONFIRMATION,
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
        approval_id="approval-task18",
        confirmation_request_id=request_payload["confirmation_request_id"],
        decision="CONFIRMED_EXECUTE",
        recorded_at_utc=request_payload["generated_at"],
        actor="dialogue.user",
    )
    path = request_path.with_name("approval-record.json")
    path.write_text(json.dumps(asdict(approval), sort_keys=True), encoding="utf-8")
    return path


def _grant(
    runner: types.ModuleType,
    config_path: Path,
    evidence_root: Path,
    request_path: Path,
) -> object:
    response = runner.run_v2(
        _request(
            runner,
            config_path,
            runner.RunnerMode.GRANT_CONFIRMATION,
            evidence_root,
            confirmation_request_path=request_path,
            approval_record_path=_approval_path(request_path),
        )
    )
    assert response.status == "SUCCESS", response.to_json()
    assert response.confirmation_token
    return response


# Production mutation caught: importing a live provider, network client, engine,
# plugin, or legacy execution module from any V2 contract/adapter.
def test_v2_modules_have_no_network_provider_or_engine_import() -> None:
    forbidden_roots = {
        "cloudpickle",
        "dill",
        "futu",
        "http",
        "pickle",
        "requests",
        "runpy",
        "socket",
        "subprocess",
        "urllib",
        "vectorbt",
    }
    forbidden_local_modules = {
        "tv_quant.cli",
        "tv_quant.downloader",
        "tv_quant.futu_downloader",
        "tv_quant.pipeline_cli",
        "tv_quant.research_pipeline",
        "tv_quant.strategy",
    }
    violations: list[str] = []

    for path in _v2_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
                imports.extend(
                    f"{node.module}.{alias.name}" if node.module else alias.name
                    for alias in node.names
                )
        for module in imports:
            lowered = module.lower()
            segments = set(lowered.split("."))
            if (
                any(
                    lowered == forbidden
                    or lowered.startswith(f"{forbidden}.")
                    for forbidden in forbidden_local_modules
                )
                or segments.intersection(forbidden_roots)
                or "plugin" in segments
                or "plugins" in segments
            ):
                violations.append(f"{path.relative_to(_REPOSITORY_ROOT)}: {module}")

    assert violations == []


# Production mutation caught: adding eval/exec/compile, dynamic import, or a
# deserialization/module-loader call to a V2 contract or adapter.
def test_v2_modules_have_no_arbitrary_execution_construct() -> None:
    forbidden_imports = {"importlib", "runpy", "pickle", "cloudpickle", "dill"}
    forbidden_named_calls = {
        "__import__",
        "compile",
        "eval",
        "exec",
    }
    forbidden_loader_calls = {
        "exec_module",
        "import_module",
        "load_module",
        "run_module",
        "run_path",
    }
    violations: list[str] = []

    for path in _v2_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".", 1)[0] for alias in node.names}
                if names.intersection(forbidden_imports):
                    violations.append(f"{path.name}:{node.lineno}: dynamic import")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".", 1)[0] in forbidden_imports:
                    violations.append(f"{path.name}:{node.lineno}: dynamic import")
            elif isinstance(node, ast.Call):
                called = ""
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id in forbidden_named_calls
                ):
                    called = node.func.id
                elif (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in forbidden_loader_calls
                ):
                    called = node.func.attr
                if called:
                    violations.append(f"{path.name}:{node.lineno}: {called}")

    assert violations == []


# Production mutation caught: wiring any V2 mode to Phase 1 pipeline/backtest,
# provider download, subprocess, socket, dynamically imported plugin, or engine.
def test_v2_runner_does_not_call_legacy_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_v2_config(tmp_path)
    import tv_quant.cli as legacy_cli
    import tv_quant.downloader as downloader
    import tv_quant.futu_downloader as futu_downloader
    import tv_quant.pipeline_cli as pipeline_cli
    import tv_quant.research_pipeline as research_pipeline
    import tv_quant.strategy as strategy

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("runner crossed the V2.1 local gate")

    monkeypatch.setattr(research_pipeline, "run_pipeline", forbidden)
    monkeypatch.setattr(strategy, "run_backtest", forbidden)
    monkeypatch.setattr(legacy_cli, "main", forbidden)
    monkeypatch.setattr(pipeline_cli, "_refresh_data", forbidden)
    monkeypatch.setattr(downloader, "download_daily", forbidden)
    monkeypatch.setattr(futu_downloader, "download_futu_daily", forbidden)
    for name in ("run", "Popen", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    forbidden_import_roots = {"requests", "socket", "subprocess", "vectorbt"}
    real_import = builtins.__import__
    real_import_module = importlib.import_module

    def guarded_import(
        name: str,
        globals_: object = None,
        locals_: object = None,
        fromlist: object = (),
        level: int = 0,
    ) -> object:
        root = name.split(".", 1)[0].lower()
        if root in forbidden_import_roots or "plugin" in name.lower():
            forbidden()
        return real_import(name, globals_, locals_, fromlist, level)

    def guarded_import_module(name: str, package: str | None = None) -> object:
        root = name.split(".", 1)[0].lower()
        if root in forbidden_import_roots or "plugin" in name.lower():
            forbidden()
        return real_import_module(name, package)

    explosive_plugin = types.ModuleType("tv_quant.plugins")
    explosive_plugin.run = forbidden  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tv_quant.plugins", explosive_plugin)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(importlib, "import_module", guarded_import_module)

    import tv_quant.contracts as contracts_package

    monkeypatch.delitem(sys.modules, "tv_quant.contracts.runner_protocol", raising=False)
    monkeypatch.delattr(contracts_package, "runner_protocol", raising=False)
    runner = real_import_module("tv_quant.contracts.runner_protocol")
    evidence_root = _evidence_root(tmp_path, monkeypatch, runner)

    validated = runner.run_v2(
        _request(runner, config_path, runner.RunnerMode.VALIDATE, evidence_root)
    )
    prepared, request_path = _prepare(runner, config_path, evidence_root)
    granted = _grant(runner, config_path, evidence_root, request_path)
    executed = runner.run_v2(
        _request(
            runner,
            config_path,
            runner.RunnerMode.EXECUTE,
            evidence_root,
            confirmation_request_path=request_path,
            confirmation_token=granted.confirmation_token,
        )
    )

    assert [validated.status, prepared.status, granted.status, executed.status] == [
        "SUCCESS",
        "SUCCESS",
        "SUCCESS",
        "NOT_IMPLEMENTED",
    ]


# Production mutation caught: implementing a second V2 hash primitive or
# pointing an artifact-owner record at a missing/non-Phase-1 function.
def test_v2_contracts_reference_existing_hash_owner() -> None:
    expected_owners = {
        "artifact_hash_binding": "bind_artifact_hashes",
        "bytes_hash": "sha256_bytes",
        "canonical_hash": "canonical_hash",
        "file_hash": "sha256_file",
    }
    owner_records = {
        owner.artifact_kind: owner
        for owner in ARTIFACT_OWNERS
        if owner.artifact_kind in expected_owners
    }
    violations: list[str] = []

    assert set(owner_records) == set(expected_owners)
    for artifact_kind, function_name in expected_owners.items():
        record = owner_records[artifact_kind]
        assert record.owner_module == "tv_quant.run_manifest"
        assert record.owner_function == function_name
        assert getattr(hash_owner, function_name, None) is not None

    for path in _v2_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported_module = (
                    node.module
                    if isinstance(node, ast.ImportFrom)
                    else ",".join(alias.name for alias in node.names)
                )
                if imported_module and "hashlib" in imported_module.split(","):
                    violations.append(f"{path.name}:{node.lineno}: hashlib")
            if isinstance(node, ast.ImportFrom):
                imported_hashes = _HASH_PRIMITIVES.intersection(
                    alias.name for alias in node.names
                )
                if imported_hashes and node.module != "tv_quant.run_manifest":
                    violations.append(
                        f"{path.name}:{node.lineno}: {node.module} {imported_hashes}"
                    )

        module = importlib.import_module(_module_name(path))
        for name in _HASH_PRIMITIVES.intersection(vars(module)):
            assert getattr(module, name) is getattr(hash_owner, name)

    assert violations == []


# Production mutation caught: persisting the one-time plaintext token in grant
# state, provisional evidence, a response after grant, or another output file.
def test_plaintext_confirmation_token_is_absent_from_persistent_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = importlib.import_module("tv_quant.contracts.runner_protocol")
    config_path = _write_v2_config(tmp_path)
    evidence_root = _evidence_root(tmp_path, monkeypatch, runner)
    _prepared, request_path = _prepare(runner, config_path, evidence_root)
    granted = _grant(runner, config_path, evidence_root, request_path)
    token = granted.confirmation_token
    assert isinstance(token, str)

    executed = runner.run_v2(
        _request(
            runner,
            config_path,
            runner.RunnerMode.EXECUTE,
            evidence_root,
            confirmation_request_path=request_path,
            confirmation_token=token,
        )
    )
    persisted_files = tuple(path for path in evidence_root.rglob("*") if path.is_file())
    persisted_bytes = {path: path.read_bytes() for path in persisted_files}

    assert persisted_files
    assert all(token.encode("utf-8") not in payload for payload in persisted_bytes.values())
    assert executed.confirmation_token is None
    assert token not in executed.to_json()
    state = json.loads(
        request_path.with_name("confirmation-state.json").read_text(encoding="utf-8")
    )
    assert "confirmation_token_hash" in state["grant"]
    assert "confirmation_token" not in state["grant"]


# Production mutation caught: omitting or mistyping recoverable/retryable/
# terminal metadata, or declaring a retryable terminal blocker.
def test_all_status_metadata_defines_recoverable_retryable_terminal() -> None:
    definitions = {definition.code: definition for definition in STATUS_DEFINITIONS}

    assert set(definitions) == set(BlockerCode)
    for code in BlockerCode:
        definition = status_definition(code)
        assert definition is definitions[code]
        assert type(definition.recoverable) is bool
        assert type(definition.retryable) is bool
        assert type(definition.terminal) is bool
        assert not definition.retryable or (
            definition.recoverable and not definition.terminal
        )


# Production mutation caught: deleting, renaming, or weakening any original
# Phase 1 test function while adding the V2.1 contract gate.
def test_phase1_suite_remains_unchanged() -> None:
    functions: list[tuple[str, str]] = []
    for relative_path in _PHASE1_TEST_FILES:
        path = _REPOSITORY_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = f"{relative_path}::{node.name}"
            if node.name.startswith("test_") and key not in _POST_PHASE1_TESTS:
                functions.append((key, ast.dump(node, include_attributes=False)))

    payload = json.dumps(functions, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()

    assert len(functions) == _PHASE1_TEST_COUNT
    assert digest == _PHASE1_TEST_AST_SHA256
