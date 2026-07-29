"""Local V2.1 request/response runner that stops before engine dispatch."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field as dataclass_field, fields, is_dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
import os
from pathlib import Path
import tempfile

import yaml

from tv_quant.run_manifest import sha256_file

from .artifact_contract import ProvisionalEvidence
from .capability_registry import (
    CapabilityRegistry,
    capability_snapshot_hash,
    load_capability_registry,
)
from .confirmation import (
    ApprovalRecord,
    ConfirmationRequest,
    FileConfirmationStore,
    create_confirmation_request,
    issue_confirmation_grant,
    validate_and_consume,
)
from .data_plan import DataPlan, build_data_plan, data_plan_hash
from .execution_assumptions import (
    ExecutionAssumptions,
    assumptions_hash,
    build_execution_assumptions,
)
from .normalized_ir import (
    NormalizedStrategyIR,
    ValidationIssue,
    normalize_strategy_spec,
    normalized_config_hash,
    normalized_config_payload,
)
from .path_safety import resolve_under_root
from .status_codes import BlockerCode, PipelineStatus, status_definition
from .strategy_v2 import StrategySpecV2, load_strategy_spec_v2


_PROTOCOL_VERSION = "v2.1"
_CAPABILITY_ID = "phase1.ema.daily.golden"
_CAPABILITY_VERSION = "v2.1"
_CONFIRMATION_TTL = timedelta(minutes=15)
_REQUEST_FILE = "confirmation-request.json"
_IR_FILE = "normalized-ir.json"
_DATA_PLAN_FILE = "data-plan.json"
_STATE_FILE = "confirmation-state.json"
_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_REGISTRY_PATH = _REPOSITORY_ROOT / "config" / "capability-registry-v2.1.json"
_TRUSTED_REPOSITORY_ROOT = _REPOSITORY_ROOT
_TRUSTED_EVIDENCE_RELATIVE = Path("reports") / "v2-runner-evidence"
_PHASE1_GOLDEN_SCOPE = {
    "strategy_family": "ema_crossover",
    "market": "US_EQUITY",
    "timeframe": "1d",
    "session": {
        "timezone": "America/New_York",
        "regular_hours_only": True,
        "calendar_id": "XNYS",
    },
    "initial_capital": {"amount": 100000, "currency": "USD"},
    "entry": {
        "node_type": "cross_above",
        "left": {
            "node_type": "indicator_ref",
            "name": "EMA",
            "parameters": {"period": 50},
            "output": "series",
            "unit": "USD",
        },
        "right": {
            "node_type": "indicator_ref",
            "name": "EMA",
            "parameters": {"period": 200},
            "output": "series",
            "unit": "USD",
        },
    },
    "exit": {
        "node_type": "cross_below",
        "left": {
            "node_type": "indicator_ref",
            "name": "EMA",
            "parameters": {"period": 50},
            "output": "series",
            "unit": "USD",
        },
        "right": {
            "node_type": "indicator_ref",
            "name": "EMA",
            "parameters": {"period": 200},
            "output": "series",
            "unit": "USD",
        },
    },
    "filters": [],
    "position_sizing": {"type": "full_capital"},
    "stop": {"enabled": False},
    "target": {"enabled": False},
    "fill_timing": "next_bar_open",
    "data": {
        "source": "validated_local_cache_first",
        "legacy_costs": {"commission_bps": "5", "slippage_bps": "5"},
    },
    "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
    "plugin": None,
    "optimization_allowed": False,
    "report_language": "zh-CN",
}


class RunnerMode(str, Enum):
    VALIDATE = "validate"
    PREPARE_CONFIRMATION = "prepare_confirmation"
    GRANT_CONFIRMATION = "grant_confirmation"
    EXECUTE = "execute"


@dataclass(frozen=True, slots=True)
class RunnerRequest:
    config_path: Path
    mode: RunnerMode
    confirmation_token: str | None = dataclass_field(default=None, repr=False)
    confirmation_request_path: Path | None = None
    approval_record_path: Path | None = None
    evidence_root: Path | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.config_path, Path):
            raise ValueError("config_path: Path required")
        if not isinstance(self.mode, RunnerMode):
            raise ValueError("mode: RunnerMode required")
        if self.confirmation_token is not None and type(self.confirmation_token) is not str:
            raise ValueError("confirmation_token: string or null required")
        for name in (
            "confirmation_request_path",
            "approval_record_path",
            "evidence_root",
        ):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Path):
                raise ValueError(f"{name}: Path or null required")


@dataclass(frozen=True, slots=True)
class RunnerResponse:
    protocol_version: str
    status: str
    blocker_code: str | None
    run_id: str
    confirmation_request_id: str | None
    confirmation_token: str | None = dataclass_field(repr=False)
    run_directory: str | None
    audit_status: str | None
    formal_result_published: bool
    report_summary_path: str | None
    next_action: str

    def to_json(self) -> str:
        """Return the stable short wire representation without logging it."""
        payload = {field.name: getattr(self, field.name) for field in fields(self)}
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True, slots=True)
class _CompiledContracts:
    ir: NormalizedStrategyIR
    data_plan: DataPlan
    assumptions: ExecutionAssumptions
    run_id: str
    capability_snapshot_hash: str


class _RunnerBlocker(Exception):
    def __init__(
        self,
        code: BlockerCode,
        *,
        run_id: str = "run-unavailable",
        confirmation_request_id: str | None = None,
    ) -> None:
        self.code = code
        self.run_id = run_id
        self.confirmation_request_id = confirmation_request_id
        super().__init__(code.value)


class _CapabilityGate:
    """Adapt the immutable registry to the normalizer's narrow validation hook."""

    def __init__(
        self,
        registry: CapabilityRegistry,
        expected_spec: StrategySpecV2,
    ) -> None:
        self._registry = registry
        self._expected_spec = expected_spec

    @staticmethod
    def _issue(message: str) -> ValidationIssue:
        return ValidationIssue(
            code=BlockerCode.STRATEGY_CAPABILITY_BLOCKER.value,
            path="strategy_family",
            severity="ERROR",
            message=message,
            recoverable=True,
            pipeline_stage="Stage 1",
            formal_result_eligible=False,
        )

    def validate_strategy(self, spec: StrategySpecV2) -> tuple[ValidationIssue, ...]:
        if spec != self._expected_spec:
            raise ValueError("runner capability gate received an unexpected specification")
        try:
            capability = self._registry.require_formal(
                _CAPABILITY_ID,
                _CAPABILITY_VERSION,
            )
        except ValueError:
            return (self._issue("required Phase 1 EMA capability is unavailable"),)
        payload = spec.payload
        static_fields = (
            "strategy_family",
            "market",
            "timeframe",
            "session",
            "initial_capital",
            "entry",
            "exit",
            "filters",
            "position_sizing",
            "stop",
            "target",
            "fill_timing",
            "data",
            "benchmark",
            "plugin",
            "optimization_allowed",
            "report_language",
        )
        actual_scope = {name: _json_value(payload[name]) for name in static_fields}
        if (
            actual_scope != _PHASE1_GOLDEN_SCOPE
            or spec.symbol not in capability.supported_market
            or payload["timeframe"] not in capability.supported_timeframes
        ):
            return (self._issue("strategy is outside the registered Phase 1 EMA scope"),)
        return ()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _timestamp(value: datetime) -> str:
    return value.isoformat()


def _compile_contracts(config_path: Path) -> _CompiledContracts:
    registry = load_capability_registry(_REGISTRY_PATH)
    spec = load_strategy_spec_v2(config_path)
    result = normalize_strategy_spec(
        spec,
        capability_registry=_CapabilityGate(registry, spec),
        source_config_hash=sha256_file(config_path),
    )
    if result.ir is None:
        code = BlockerCode(result.issues[0].code)
        raise _RunnerBlocker(code)
    ir = result.ir
    plan = build_data_plan(ir, registry)
    snapshot_hash = capability_snapshot_hash(registry)
    assumptions = build_execution_assumptions(
        ir,
        plan,
        {
            "cost_profile_id": plan.primary.cost_profile_requirement,
            "corporate_action_profile_id": "corporate-actions.v1",
            "benchmark_protocol_id": "buy-and-hold.v1",
            "benchmark_protocol_version": "v1",
            "capability_snapshot_hash": snapshot_hash,
            "normalizer_version": "v2.1",
        },
    )
    return _CompiledContracts(
        ir=ir,
        data_plan=plan,
        assumptions=assumptions,
        run_id=f"run-{normalized_config_hash(ir)[:16]}",
        capability_snapshot_hash=snapshot_hash,
    )


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if value is None or type(value) in (bool, int, str):
        return value
    raise ValueError("provisional evidence contains a non-JSON value")


def _serialize(value: object) -> str:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("duplicate JSON field")
        payload[key] = value
    return payload


def _read_object(path: Path) -> dict[str, object]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_fields,
    )
    if type(payload) is not dict:
        raise ValueError("JSON object required")
    return payload


def _trusted_directory(path: Path, *, bootstrap: bool) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        if not bootstrap:
            raise
        path.mkdir()
        resolved = path.resolve(strict=True)
    if resolved != path or not resolved.is_dir():
        raise ValueError("trusted directory boundary required")
    return resolved


def _evidence_root(request: RunnerRequest, *, bootstrap: bool = False) -> Path:
    if request.evidence_root is None:
        raise ValueError("evidence_root required")
    try:
        repository_root = _TRUSTED_REPOSITORY_ROOT.resolve(strict=True)
        if not repository_root.is_dir():
            raise ValueError("trusted repository directory required")
        reports_root = _trusted_directory(
            repository_root / _TRUSTED_EVIDENCE_RELATIVE.parent,
            bootstrap=bootstrap,
        )
        trusted_root = _trusted_directory(
            reports_root / _TRUSTED_EVIDENCE_RELATIVE.name,
            bootstrap=bootstrap,
        )
        root = request.evidence_root.resolve(strict=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("evidence_root: existing directory required") from exc
    if not root.is_dir() or root != trusted_root:
        raise ValueError("evidence_root: existing directory required")
    return root


def _contained_file(root: Path, path: Path | None) -> Path:
    if path is None:
        raise ValueError("required path missing")
    try:
        relative = path.resolve(strict=True).relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("path must be an existing file under evidence_root") from exc
    candidate = resolve_under_root(root, relative.as_posix())
    if not candidate.is_file():
        raise ValueError("path must be an existing file under evidence_root")
    return candidate


def _run_file(root: Path, contracts: _CompiledContracts, filename: str) -> Path:
    return resolve_under_root(root, f"{contracts.run_id}/{filename}")


def _state_path(root: Path, contracts: _CompiledContracts) -> Path:
    return _run_file(root, contracts, _STATE_FILE)


def _read_confirmation_request(
    root: Path,
    path: Path | None,
    contracts: _CompiledContracts,
) -> tuple[ConfirmationRequest, Path]:
    request_path = _contained_file(root, path)
    if request_path != _run_file(root, contracts, _REQUEST_FILE):
        raise ValueError("canonical confirmation request path required")
    confirmation = ConfirmationRequest(**_read_object(request_path))
    expected = create_confirmation_request(
        contracts.ir,
        contracts.data_plan,
        contracts.assumptions,
        confirmation.generated_at,
        confirmation.expires_at,
    )
    if confirmation != expected:
        raise ValueError("confirmation request does not match compiled contracts")
    evidence_bindings = (
        (
            _run_file(root, contracts, _IR_FILE),
            _json_value(normalized_config_payload(contracts.ir)),
        ),
        (
            _run_file(root, contracts, _DATA_PLAN_FILE),
            _json_value(contracts.data_plan),
        ),
    )
    for evidence_path, expected_payload in evidence_bindings:
        if _read_object(_contained_file(root, evidence_path)) != expected_payload:
            raise ValueError("provisional evidence does not match compiled contracts")
    return confirmation, request_path


def _response(
    *,
    status: PipelineStatus,
    run_id: str,
    blocker_code: BlockerCode | None = None,
    confirmation_request_id: str | None = None,
    confirmation_token: str | None = None,
    next_action: str,
) -> RunnerResponse:
    return RunnerResponse(
        protocol_version=_PROTOCOL_VERSION,
        status=status.value,
        blocker_code=blocker_code.value if blocker_code is not None else None,
        run_id=run_id,
        confirmation_request_id=confirmation_request_id,
        confirmation_token=confirmation_token,
        run_directory=None,
        audit_status=None,
        formal_result_published=False,
        report_summary_path=None,
        next_action=next_action,
    )


def _blocked(
    code: BlockerCode,
    *,
    run_id: str,
    confirmation_request_id: str | None = None,
) -> RunnerResponse:
    definition = status_definition(code)
    return _response(
        status=definition.status,
        run_id=run_id,
        blocker_code=code,
        confirmation_request_id=confirmation_request_id,
        next_action=definition.user_action,
    )


def _validate(contracts: _CompiledContracts) -> RunnerResponse:
    return _response(
        status=PipelineStatus.SUCCESS,
        run_id=contracts.run_id,
        next_action="PREPARE_CONFIRMATION",
    )


def _prepare(request: RunnerRequest, contracts: _CompiledContracts) -> RunnerResponse:
    root = _evidence_root(request, bootstrap=True)
    run_directory = resolve_under_root(root, contracts.run_id)
    now = _utc_now()
    confirmation = create_confirmation_request(
        contracts.ir,
        contracts.data_plan,
        contracts.assumptions,
        _timestamp(now),
        _timestamp(now + _CONFIRMATION_TTL),
    )
    relative_paths = (
        f"{contracts.run_id}/{_REQUEST_FILE}",
        f"{contracts.run_id}/{_IR_FILE}",
        f"{contracts.run_id}/{_DATA_PLAN_FILE}",
    )
    evidence = ProvisionalEvidence(
        run_id=contracts.run_id,
        evidence_kind="confirmation",
        paths=relative_paths,
        config_hash=normalized_config_hash(contracts.ir),
        data_plan_hash=data_plan_hash(contracts.data_plan),
        capability_snapshot_hash=contracts.capability_snapshot_hash,
        status="PROVISIONAL",
        formal_result_published=False,
    )
    payloads = (
        confirmation,
        normalized_config_payload(contracts.ir),
        contracts.data_plan,
    )
    staging_directory = Path(
        tempfile.mkdtemp(prefix=f".{contracts.run_id}.", dir=root)
    )
    staging_paths = tuple(staging_directory / Path(path).name for path in relative_paths)
    try:
        for path, payload in zip(staging_paths, payloads, strict=True):
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(_serialize(payload))
                handle.write("\n")
        os.replace(staging_directory, run_directory)
    except Exception:
        for path in staging_paths:
            path.unlink(missing_ok=True)
        staging_directory.rmdir()
        raise
    evidence.resolved_paths(root)
    return _response(
        status=PipelineStatus.SUCCESS,
        run_id=contracts.run_id,
        confirmation_request_id=confirmation.confirmation_request_id,
        next_action="AWAIT_USER_CONFIRMATION",
    )


def _grant(request: RunnerRequest, contracts: _CompiledContracts) -> RunnerResponse:
    root = _evidence_root(request)
    confirmation, _request_path = _read_confirmation_request(
        root,
        request.confirmation_request_path,
        contracts,
    )
    approval_path = _contained_file(root, request.approval_record_path)
    approval = ApprovalRecord(**_read_object(approval_path))
    handoff = issue_confirmation_grant(
        confirmation,
        approval,
        _timestamp(_utc_now()),
    )
    persisted = FileConfirmationStore(_state_path(root, contracts)).persist_grant(
        handoff.grant
    )
    if persisted.outcome != "SUCCESS":
        assert persisted.blocker_code is not None
        return _blocked(
            persisted.blocker_code,
            run_id=contracts.run_id,
            confirmation_request_id=confirmation.confirmation_request_id,
        )
    return _response(
        status=PipelineStatus.SUCCESS,
        run_id=contracts.run_id,
        confirmation_request_id=confirmation.confirmation_request_id,
        confirmation_token=handoff.confirmation_token,
        next_action="EXECUTE_WITH_CONFIRMATION_TOKEN",
    )


def _execute(request: RunnerRequest, contracts: _CompiledContracts) -> RunnerResponse:
    if not request.confirmation_token:
        return _blocked(
            BlockerCode.CONFIRMATION_REQUIRED,
            run_id=contracts.run_id,
        )
    root = _evidence_root(request)
    confirmation, _request_path = _read_confirmation_request(
        root,
        request.confirmation_request_path,
        contracts,
    )
    state_path = _state_path(root, contracts)
    audit = validate_and_consume(
        request.confirmation_token,
        normalized_config_hash(contracts.ir),
        data_plan_hash(contracts.data_plan),
        assumptions_hash(contracts.assumptions),
        FileConfirmationStore(state_path),
        expected_confirmation_request_id=confirmation.confirmation_request_id,
    )
    if audit.outcome != "SUCCESS":
        assert audit.blocker_code is not None
        public_code = (
            BlockerCode.CONFIRMATION_INVALID
            if audit.blocker_code is BlockerCode.CONFIRMATION_HASH_MISMATCH
            else audit.blocker_code
        )
        return _blocked(
            public_code,
            run_id=contracts.run_id,
            confirmation_request_id=confirmation.confirmation_request_id,
        )
    if audit.confirmation_request_id != confirmation.confirmation_request_id:
        return _blocked(
            BlockerCode.CONFIRMATION_INVALID,
            run_id=contracts.run_id,
            confirmation_request_id=confirmation.confirmation_request_id,
        )
    return _response(
        status=PipelineStatus.NOT_IMPLEMENTED,
        run_id=contracts.run_id,
        blocker_code=BlockerCode.EXECUTION_CAPABILITY_NOT_IMPLEMENTED,
        confirmation_request_id=confirmation.confirmation_request_id,
        next_action="WAIT_FOR_V2_3_ENGINE",
    )


def run_v2(request: RunnerRequest) -> RunnerResponse:
    """Dispatch one local V2.1 gate request without provider or engine execution."""
    if type(request) is not RunnerRequest:
        raise ValueError("RunnerRequest required")
    try:
        contracts = _compile_contracts(request.config_path)
        if request.mode is RunnerMode.VALIDATE:
            return _validate(contracts)
        if request.mode is RunnerMode.PREPARE_CONFIRMATION:
            return _prepare(request, contracts)
        if request.mode is RunnerMode.GRANT_CONFIRMATION:
            return _grant(request, contracts)
        if request.mode is RunnerMode.EXECUTE:
            return _execute(request, contracts)
    except _RunnerBlocker as blocker:
        return _blocked(
            blocker.code,
            run_id=blocker.run_id,
            confirmation_request_id=blocker.confirmation_request_id,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError, yaml.YAMLError):
        code = (
            BlockerCode.CONFIG_VALIDATION_BLOCKER
            if request.mode in {RunnerMode.VALIDATE, RunnerMode.PREPARE_CONFIRMATION}
            else BlockerCode.CONFIRMATION_INVALID
        )
        return _blocked(code, run_id="run-unavailable")
    raise AssertionError("unreachable RunnerMode")


__all__ = (
    "RunnerMode",
    "RunnerRequest",
    "RunnerResponse",
    "run_v2",
)
