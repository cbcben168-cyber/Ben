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
from tv_quant.contracts.artifact_contract import ARTIFACT_OWNERS, ArtifactOwner
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
_EXPECTED_V2_SOURCE_INVENTORY = (
    "src/tv_quant/adapters/__init__.py",
    "src/tv_quant/adapters/phase1_config_adapter.py",
    "src/tv_quant/contracts/__init__.py",
    "src/tv_quant/contracts/artifact_contract.py",
    "src/tv_quant/contracts/ast_contract.py",
    "src/tv_quant/contracts/capability_registry.py",
    "src/tv_quant/contracts/confirmation.py",
    "src/tv_quant/contracts/data_plan.py",
    "src/tv_quant/contracts/execution_assumptions.py",
    "src/tv_quant/contracts/normalized_ir.py",
    "src/tv_quant/contracts/numeric.py",
    "src/tv_quant/contracts/path_safety.py",
    "src/tv_quant/contracts/runner_protocol.py",
    "src/tv_quant/contracts/schema_contract.py",
    "src/tv_quant/contracts/status_codes.py",
    "src/tv_quant/contracts/strategy_v2.py",
    "src/tv_quant/contracts/template_contract.py",
)
_HASH_PRIMITIVES = {
    "bind_artifact_hashes",
    "canonical_hash",
    "sha256_bytes",
    "sha256_file",
}
_EXPECTED_ARTIFACT_OWNERS = (
    ("canonical_hash", "tv_quant.run_manifest", "canonical_hash", True),
    ("file_hash", "tv_quant.run_manifest", "sha256_file", True),
    ("bytes_hash", "tv_quant.run_manifest", "sha256_bytes", True),
    (
        "artifact_hash_binding",
        "tv_quant.run_manifest",
        "bind_artifact_hashes",
        True,
    ),
    (
        "data_provenance",
        "tv_quant.research_pipeline",
        "write_data_provenance",
        True,
    ),
    ("backtest_audit", "tv_quant.backtest_audit", "audit_backtest", True),
    ("formal_report", "tv_quant.reporting", "write_reports", True),
)
_OWNER_PRIMITIVES = {
    "audit_backtest": "tv_quant.backtest_audit",
    "bind_artifact_hashes": "tv_quant.run_manifest",
    "build_manifest": "tv_quant.run_manifest",
    "canonical_hash": "tv_quant.run_manifest",
    "sha256_bytes": "tv_quant.run_manifest",
    "sha256_file": "tv_quant.run_manifest",
    "write_data_provenance": "tv_quant.research_pipeline",
    "write_manifest": "tv_quant.run_manifest",
    "write_reports": "tv_quant.reporting",
}
_FORMAL_WRITERS = {
    "audit_backtest",
    "bind_artifact_hashes",
    "build_manifest",
    "write_data_provenance",
    "write_manifest",
    "write_reports",
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
_PHASE1_FILE_COUNT = 18
_PHASE1_FULL_AST_SHA256 = (
    "3f4b9a1a4a113555d84793a3e98dbbb9a02dcc28672348e8d021fc058e52ff09"
)


def _v2_sources() -> tuple[Path, ...]:
    return tuple(
        sorted(path for root in _V2_SOURCE_ROOTS for path in root.rglob("*.py"))
    )


def _network_import_violations(paths: tuple[Path, ...]) -> list[str]:
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
    for path in paths:
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
                violations.append(f"{path}: {module}")
    return violations


def _import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", 1)[0]
                aliases[local_name] = alias.name if alias.asname else local_name
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for alias in node.names:
                if alias.name == "*":
                    continue
                local_name = alias.asname or alias.name
                aliases[local_name] = (
                    f"{module}.{alias.name}" if module else alias.name
                )
    return aliases


def _qualified_name(node: ast.expr, aliases: Mapping[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        parent = _qualified_name(node.value, aliases)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _arbitrary_execution_violations(paths: tuple[Path, ...]) -> list[str]:
    forbidden_imports = {"importlib", "runpy", "pickle", "cloudpickle", "dill"}
    forbidden_calls = {
        "__import__",
        "builtins.__import__",
        "builtins.compile",
        "builtins.eval",
        "builtins.exec",
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
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _import_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".", 1)[0] for alias in node.names}
                if names.intersection(forbidden_imports):
                    violations.append(f"{path.name}:{node.lineno}: dynamic import")
            elif isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".", 1)[0] in forbidden_imports:
                    violations.append(f"{path.name}:{node.lineno}: dynamic import")
            elif isinstance(node, ast.Call):
                called = _qualified_name(node.func, aliases)
                if (
                    called in forbidden_calls
                    or called.rsplit(".", 1)[-1] in forbidden_loader_calls
                ):
                    violations.append(f"{path.name}:{node.lineno}: {called}")
    return violations


def _owner_static_violations(
    records: tuple[ArtifactOwner, ...], paths: tuple[Path, ...]
) -> list[str]:
    violations: list[str] = []
    owner_table = tuple(
        (
            owner.artifact_kind,
            owner.owner_module,
            owner.owner_function,
            owner.required,
        )
        for owner in records
    )
    if len({owner.artifact_kind for owner in records}) != len(records):
        violations.append("duplicate artifact owner")
    if owner_table != _EXPECTED_ARTIFACT_OWNERS:
        violations.append("artifact owner table mismatch")
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        aliases = _import_aliases(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name.split(".", 1)[0] == "hashlib" for alias in node.names):
                    violations.append(f"{path.name}:{node.lineno}: duplicate hash owner")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.module.split(".", 1)[0] == "hashlib":
                    violations.append(f"{path.name}:{node.lineno}: duplicate hash owner")
                for alias in node.names:
                    expected_module = _OWNER_PRIMITIVES.get(alias.name)
                    if expected_module is not None and node.module != expected_module:
                        violations.append(
                            f"{path.name}:{node.lineno}: wrong owner for {alias.name}"
                        )
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in _OWNER_PRIMITIVES:
                    violations.append(
                        f"{path.name}:{node.lineno}: duplicate owner definition {node.name}"
                    )
            elif isinstance(node, ast.Call):
                called = _qualified_name(node.func, aliases)
                primitive = called.rsplit(".", 1)[-1]
                if primitive in _FORMAL_WRITERS:
                    violations.append("formal writer call")
                expected_module = _OWNER_PRIMITIVES.get(primitive)
                if (
                    expected_module is not None
                    and "." in called
                    and called != f"{expected_module}.{primitive}"
                ):
                    violations.append(
                        f"{path.name}:{node.lineno}: wrong owner call {called}"
                    )
    return violations


def _phase1_full_ast_snapshot(sources: Mapping[str, str]) -> tuple[int, str]:
    modules: list[tuple[str, str]] = []
    for relative_path in sorted(sources):
        source = sources[relative_path]
        tree = ast.parse(source, filename=relative_path)
        if relative_path == "tests/pipeline/test_run_manifest.py":
            tree.body = [
                node
                for node in tree.body
                if not (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and f"{relative_path}::{node.name}" in _POST_PHASE1_TESTS
                )
            ]
            for node in tree.body:
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "tv_quant.run_manifest"
                ):
                    node.names = [
                        alias for alias in node.names if alias.name != "sha256_bytes"
                    ]
        modules.append((relative_path, ast.dump(tree, include_attributes=False)))
    payload = json.dumps(modules, ensure_ascii=False, separators=(",", ":"))
    return len(modules), hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relevant_phase1_conftests(test_files: tuple[Path, ...]) -> tuple[Path, ...]:
    conftests: set[Path] = set()
    for test_file in test_files:
        reached_tests_directory = False
        for parent in test_file.parents:
            candidate = parent / "conftest.py"
            if candidate.is_file():
                conftests.add(candidate)
            if reached_tests_directory:
                break
            reached_tests_directory = parent.name == "tests"
    return tuple(sorted(conftests))


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
def test_v2_modules_have_no_network_provider_or_engine_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = _v2_sources()
    inventory = tuple(
        path.relative_to(_REPOSITORY_ROOT).as_posix() for path in sources
    )
    assert inventory == _EXPECTED_V2_SOURCE_INVENTORY
    assert _network_import_violations(sources) == []

    nested_root = tmp_path / "contracts"
    nested_module = nested_root / "nested" / "provider.py"
    nested_module.parent.mkdir(parents=True)
    nested_module.write_text("import socket\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "_V2_SOURCE_ROOTS", (nested_root,))
    mutated_sources = _v2_sources()
    mutation_failures = []
    if nested_module not in mutated_sources:
        mutation_failures.append("nested V2 module omitted from inventory")
    if not _network_import_violations(mutated_sources):
        mutation_failures.append("nested provider import accepted")
    assert mutation_failures == []


# Production mutation caught: adding eval/exec/compile, dynamic import, or a
# deserialization/module-loader call to a V2 contract or adapter.
def test_v2_modules_have_no_arbitrary_execution_construct(tmp_path: Path) -> None:
    assert _arbitrary_execution_violations(_v2_sources()) == []

    bypass = tmp_path / "qualified_builtins.py"
    bypass.write_text(
        "import builtins as safe\n"
        "from builtins import eval as evaluator\n"
        "safe.eval('1 + 1')\n"
        "safe.exec('value = 1')\n"
        "safe.compile('1', '<test>', 'eval')\n"
        "safe.__import__('socket')\n"
        "evaluator('1 + 1')\n",
        encoding="utf-8",
    )
    violations = _arbitrary_execution_violations((bypass,))
    assert len(violations) == 5, violations


# Production mutation caught: wiring any V2 mode to Phase 1 pipeline/backtest,
# provider download, subprocess, socket, dynamically imported plugin, or engine.
def test_v2_runner_does_not_call_legacy_pipeline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_v2_config(tmp_path)
    import tv_quant.backtest_audit as backtest_audit
    import tv_quant.cli as legacy_cli
    import tv_quant.downloader as downloader
    import tv_quant.futu_downloader as futu_downloader
    import tv_quant.pipeline_cli as pipeline_cli
    import tv_quant.reporting as reporting
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
    for module, names in (
        (hash_owner, ("bind_artifact_hashes", "build_manifest", "write_manifest")),
        (research_pipeline, ("write_data_provenance",)),
        (backtest_audit, ("audit_backtest",)),
        (reporting, ("write_reports",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    for name in ("run", "Popen", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    forbidden_import_roots = {
        "futu",
        "http",
        "requests",
        "socket",
        "subprocess",
        "urllib",
        "vectorbt",
    }
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
    for name in ("compile", "eval", "exec"):
        monkeypatch.setattr(builtins, name, forbidden)
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


# Production mutation caught: duplicating an owner row/definition, redirecting
# a canonical primitive, or invoking a manifest/provenance/audit/report writer.
def test_v2_contracts_reference_existing_hash_owner(tmp_path: Path) -> None:
    owner_table = tuple(
        (
            owner.artifact_kind,
            owner.owner_module,
            owner.owner_function,
            owner.required,
        )
        for owner in ARTIFACT_OWNERS
    )
    assert owner_table == _EXPECTED_ARTIFACT_OWNERS
    assert len({owner.artifact_kind for owner in ARTIFACT_OWNERS}) == len(
        ARTIFACT_OWNERS
    )
    for owner in ARTIFACT_OWNERS:
        module = importlib.import_module(owner.owner_module)
        assert callable(getattr(module, owner.owner_function, None))
    for function_name, module_name in _OWNER_PRIMITIVES.items():
        module = importlib.import_module(module_name)
        assert callable(getattr(module, function_name, None))

    violations = _owner_static_violations(ARTIFACT_OWNERS, _v2_sources())
    for path in _v2_sources():
        module = importlib.import_module(_module_name(path))
        for name in _HASH_PRIMITIVES.intersection(vars(module)):
            assert getattr(module, name) is getattr(hash_owner, name)
    assert violations == []

    writer = tmp_path / "formal_writer.py"
    writer.write_text(
        "from tv_quant.reporting import write_reports as publish\n"
        "publish(None, None, None, None, None)\n",
        encoding="utf-8",
    )
    bypass_violations = _owner_static_violations(
        ARTIFACT_OWNERS + (ARTIFACT_OWNERS[0],),
        (writer,),
    )
    assert "duplicate artifact owner" in bypass_violations
    assert "formal writer call" in bypass_violations


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


# Production mutation caught: weakening any original Phase 1 test/support
# module or adding a relevant conftest that skips or rewrites collection.
def test_phase1_suite_remains_unchanged(tmp_path: Path) -> None:
    sources = {
        relative_path: (_REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in _PHASE1_TEST_FILES
    }
    count, digest = _phase1_full_ast_snapshot(sources)
    assert count == _PHASE1_FILE_COUNT
    assert digest == _PHASE1_FULL_AST_SHA256
    phase1_paths = tuple(_REPOSITORY_ROOT / path for path in _PHASE1_TEST_FILES)
    assert _relevant_phase1_conftests(phase1_paths) == ()

    baseline = (
        "import pytest\n"
        "pytestmark = []\n"
        "ENABLED = True\n"
        "def helper(): return ENABLED\n"
        "def test_guard(): assert helper()\n"
    )
    weakened = baseline.replace(
        "pytestmark = []\nENABLED = True\ndef helper(): return ENABLED",
        "pytestmark = pytest.mark.skip(reason='disabled')\n"
        "ENABLED = False\ndef helper(): return True",
    )
    support_failures = []
    if _phase1_full_ast_snapshot({"tests/test_guard.py": baseline}) == (
        _phase1_full_ast_snapshot({"tests/test_guard.py": weakened})
    ):
        support_failures.append("module support weakening accepted")

    test_file = tmp_path / "tests" / "pipeline" / "test_guard.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(baseline, encoding="utf-8")
    conftest = test_file.parents[1] / "conftest.py"
    conftest.write_text("pytest_plugins = []\n", encoding="utf-8")
    if conftest not in _relevant_phase1_conftests((test_file,)):
        support_failures.append("relevant conftest omitted")
    root_conftest = test_file.parents[2] / "conftest.py"
    root_conftest.write_text("pytest_plugins = []\n", encoding="utf-8")
    if root_conftest not in _relevant_phase1_conftests((test_file,)):
        support_failures.append("repository-root conftest omitted")
    assert support_failures == []
