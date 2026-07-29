"""Typed V2.1 confirmation request, grant state, and one-time token handoff."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
from types import MappingProxyType
from typing import BinaryIO, Protocol

from tv_quant.run_manifest import canonical_hash, sha256_bytes

from .data_plan import DataPlan, DatasetRequirement, data_plan_hash as compute_data_plan_hash
from .execution_assumptions import ExecutionAssumptions, assumptions_hash
from .normalized_ir import NormalizedStrategyIR, normalized_config_hash
from .status_codes import BlockerCode


_SHA256_HEX = re.compile(r"[0-9a-f]{64}\Z")
_STABLE_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]+\Z")
_REQUEST_SUMMARY_FIELDS = frozenset(
    {
        "strategy_id",
        "strategy_family",
        "strategy_name",
        "symbol",
        "market",
        "timeframe",
        "fill_timing",
        "optimization_allowed",
        "report_language",
    }
)
_DATA_PLAN_SUMMARY_FIELDS = frozenset({"primary", "auxiliary", "requested_range"})
_REQUEST_ID_FIELDS = (
    "schema_version",
    "normalized_config_hash",
    "data_plan_hash",
    "assumptions_hash",
    "config_summary",
    "data_plan_summary",
    "cost_profile_id",
    "corporate_action_profile_id",
    "generated_at",
    "expires_at",
)
_CONFIRMATION_STATE_SCHEMA = "v2.1"
_CONFIRMATION_STATE_VERSION = 1
_CONFIRMATION_STATE_FIELDS = frozenset({"schema_version", "state_version", "grant"})
_GRANT_STATE_FIELDS = frozenset(
    {
        "confirmation_request_id",
        "confirmation_token_hash",
        "bound_config_hash",
        "bound_data_plan_hash",
        "bound_assumptions_hash",
        "issued_at",
        "expires_at",
        "single_use",
        "consumed_at",
    }
)
_LOCK_TIMEOUT_SECONDS = 5.0
_LOCK_RETRY_SECONDS = 0.01


def _string(value: object, path: str) -> str:
    if type(value) is not str or not value:
        raise ValueError(f"{path}: non-empty string required")
    return value


def _stable_identifier(value: object, path: str) -> str:
    identifier = _string(value, path)
    if not _STABLE_IDENTIFIER.fullmatch(identifier):
        raise ValueError(f"{path}: stable identifier required")
    return identifier


def _sha256(value: object, path: str) -> str:
    digest = _string(value, path)
    if not _SHA256_HEX.fullmatch(digest):
        raise ValueError(f"{path}: lowercase SHA-256 hex required")
    return digest


def _utc_datetime(value: object, path: str) -> datetime:
    timestamp = _string(value, path)
    candidate = f"{timestamp[:-1]}+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError(f"{path}: ISO-8601 UTC timestamp required") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{path}: UTC timestamp required")
    return parsed


def _frozen_value(value: object, path: str) -> object:
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise ValueError(f"{path}: object keys must be strings")
        return MappingProxyType(
            {key: _frozen_value(value[key], f"{path}.{key}") for key in sorted(value)}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_frozen_value(item, f"{path}[{index}]") for index, item in enumerate(value))
    if value is None or type(value) in (bool, int, str):
        return value
    raise ValueError(f"{path}: immutable JSON-like value required")


def _frozen_summary(
    value: object,
    path: str,
    expected_fields: frozenset[str],
) -> Mapping[str, object]:
    frozen = _frozen_value(value, path)
    if not isinstance(frozen, Mapping) or set(frozen) != expected_fields:
        raise ValueError(f"{path}: exact summary fields required")
    return frozen


def _plain_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain_value(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_plain_value(item) for item in value]
    return value


def _confirmation_request_id(fields: Mapping[str, object]) -> str:
    if set(fields) != set(_REQUEST_ID_FIELDS):
        raise ValueError("request ID fields are incomplete")
    return "confirmation-request-" + canonical_hash(
        {name: _plain_value(fields[name]) for name in _REQUEST_ID_FIELDS}
    )


def _request_id_fields(request: ConfirmationRequest) -> Mapping[str, object]:
    return {name: getattr(request, name) for name in _REQUEST_ID_FIELDS}


@dataclass(frozen=True, slots=True)
class ApprovalRecord:
    """A typed dialogue-layer decision; free-form chat is never accepted here."""

    approval_id: str
    confirmation_request_id: str
    decision: str
    recorded_at_utc: str
    actor: str

    def __post_init__(self) -> None:
        _stable_identifier(self.approval_id, "approval_id")
        _stable_identifier(self.confirmation_request_id, "confirmation_request_id")
        _string(self.decision, "decision")
        if self.decision != "CONFIRMED_EXECUTE":
            raise ValueError("decision: must equal CONFIRMED_EXECUTE")
        _utc_datetime(self.recorded_at_utc, "recorded_at_utc")
        _stable_identifier(self.actor, "actor")


@dataclass(frozen=True, slots=True)
class ConfirmationRequest:
    """Immutable request binding the normalized strategy, data plan, and assumptions."""

    confirmation_request_id: str
    schema_version: str
    normalized_config_hash: str
    data_plan_hash: str
    assumptions_hash: str
    config_summary: Mapping[str, object]
    data_plan_summary: Mapping[str, object]
    cost_profile_id: str
    corporate_action_profile_id: str
    generated_at: str
    expires_at: str

    def __post_init__(self) -> None:
        _stable_identifier(self.confirmation_request_id, "confirmation_request_id")
        _string(self.schema_version, "schema_version")
        if self.schema_version != "v2.1":
            raise ValueError("schema_version: must equal v2.1")
        _sha256(self.normalized_config_hash, "normalized_config_hash")
        _sha256(self.data_plan_hash, "data_plan_hash")
        _sha256(self.assumptions_hash, "assumptions_hash")
        object.__setattr__(
            self,
            "config_summary",
            _frozen_summary(
                self.config_summary,
                "config_summary",
                _REQUEST_SUMMARY_FIELDS,
            ),
        )
        object.__setattr__(
            self,
            "data_plan_summary",
            _frozen_summary(
                self.data_plan_summary,
                "data_plan_summary",
                _DATA_PLAN_SUMMARY_FIELDS,
            ),
        )
        _stable_identifier(self.cost_profile_id, "cost_profile_id")
        _stable_identifier(self.corporate_action_profile_id, "corporate_action_profile_id")
        generated = _utc_datetime(self.generated_at, "generated_at")
        expires = _utc_datetime(self.expires_at, "expires_at")
        if expires <= generated:
            raise ValueError("expires_at: must be after generated_at")


@dataclass(frozen=True, slots=True)
class ConfirmationGrant:
    """Serializable single-use grant state containing only the token hash."""

    confirmation_request_id: str
    confirmation_token_hash: str
    bound_config_hash: str
    bound_data_plan_hash: str
    bound_assumptions_hash: str
    issued_at: str
    expires_at: str
    single_use: bool
    consumed_at: str | None

    def __post_init__(self) -> None:
        _stable_identifier(self.confirmation_request_id, "confirmation_request_id")
        _sha256(self.confirmation_token_hash, "confirmation_token_hash")
        _sha256(self.bound_config_hash, "bound_config_hash")
        _sha256(self.bound_data_plan_hash, "bound_data_plan_hash")
        _sha256(self.bound_assumptions_hash, "bound_assumptions_hash")
        issued = _utc_datetime(self.issued_at, "issued_at")
        expires = _utc_datetime(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError("expires_at: must be after issued_at")
        if self.single_use is not True:
            raise ValueError("single_use: must equal true")
        if self.consumed_at is not None:
            consumed = _utc_datetime(self.consumed_at, "consumed_at")
            if consumed < issued:
                raise ValueError("consumed_at: must not precede issued_at")


@dataclass(frozen=True, slots=True)
class ConfirmationAuditRecord:
    """Minimal caller-visible confirmation decision with no token or digest data."""

    confirmation_request_id: str | None
    outcome: str
    blocker_code: BlockerCode | None
    evaluated_at: str
    consumed_at: str | None

    def __post_init__(self) -> None:
        if self.confirmation_request_id is not None:
            _stable_identifier(self.confirmation_request_id, "confirmation_request_id")
        if self.outcome not in {"SUCCESS", "BLOCKED"}:
            raise ValueError("outcome: must equal SUCCESS or BLOCKED")
        if self.outcome == "SUCCESS" and self.blocker_code is not None:
            raise ValueError("blocker_code: successful outcome cannot have blocker")
        if self.outcome == "BLOCKED" and not isinstance(self.blocker_code, BlockerCode):
            raise ValueError("blocker_code: blocked outcome requires BlockerCode")
        _utc_datetime(self.evaluated_at, "evaluated_at")
        if self.consumed_at is not None:
            _utc_datetime(self.consumed_at, "consumed_at")


class ConfirmationStore(Protocol):
    """Minimal persistence boundary for issued grants and atomic consumption."""

    def persist_grant(self, grant: ConfirmationGrant) -> ConfirmationAuditRecord:
        """Persist a newly issued grant without replacing official state."""
        ...

    def validate_and_consume(
        self,
        confirmation_token: str,
        expected_config_hash: str,
        expected_data_plan_hash: str,
        expected_assumptions_hash: str,
    ) -> ConfirmationAuditRecord:
        """Validate all bindings and atomically consume the official grant."""
        ...


class _LockBackend(Protocol):
    def acquire(self, handle: BinaryIO) -> None: ...

    def release(self, handle: BinaryIO) -> None: ...


class _StorageFailure(Exception):
    pass


class _InvalidState(Exception):
    pass


class _WindowsLockBackend:
    def __init__(
        self,
        msvcrt_module: object,
        *,
        timeout_seconds: float = _LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self._msvcrt = msvcrt_module
        self._timeout_seconds = timeout_seconds

    def acquire(self, handle: BinaryIO) -> None:
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            handle.seek(0)
            try:
                self._msvcrt.locking(  # type: ignore[attr-defined]
                    handle.fileno(),
                    self._msvcrt.LK_NBLCK,  # type: ignore[attr-defined]
                    1,
                )
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise _StorageFailure from exc
                time.sleep(_LOCK_RETRY_SECONDS)

    def release(self, handle: BinaryIO) -> None:
        handle.seek(0)
        self._msvcrt.locking(  # type: ignore[attr-defined]
            handle.fileno(),
            self._msvcrt.LK_UNLCK,  # type: ignore[attr-defined]
            1,
        )


class _PosixLockBackend:
    def __init__(
        self,
        fcntl_module: object,
        *,
        timeout_seconds: float = _LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self._fcntl = fcntl_module
        self._timeout_seconds = timeout_seconds

    def acquire(self, handle: BinaryIO) -> None:
        deadline = time.monotonic() + self._timeout_seconds
        while True:
            try:
                self._fcntl.flock(  # type: ignore[attr-defined]
                    handle.fileno(),
                    self._fcntl.LOCK_EX | self._fcntl.LOCK_NB,  # type: ignore[attr-defined]
                )
                return
            except OSError as exc:
                if time.monotonic() >= deadline:
                    raise _StorageFailure from exc
                time.sleep(_LOCK_RETRY_SECONDS)

    def release(self, handle: BinaryIO) -> None:
        self._fcntl.flock(  # type: ignore[attr-defined]
            handle.fileno(),
            self._fcntl.LOCK_UN,  # type: ignore[attr-defined]
        )


class _UnsupportedLockBackend:
    def acquire(self, _handle: BinaryIO) -> None:
        raise _StorageFailure

    def release(self, _handle: BinaryIO) -> None:
        return None


def _platform_lock_backend() -> _LockBackend:
    if os.name == "nt":
        import msvcrt

        return _WindowsLockBackend(msvcrt)
    if os.name == "posix":
        import fcntl

        return _PosixLockBackend(fcntl)
    return _UnsupportedLockBackend()


class FileConfirmationStore:
    """Path-bound store whose file lock covers read, validation, and replacement."""

    def __init__(
        self,
        path: Path,
        *,
        _clock: Callable[[], datetime] | None = None,
        _lock_backend: _LockBackend | None = None,
    ) -> None:
        self._path = Path(path)
        self._lock_path = self._path.with_name(f".{self._path.name}.lock")
        self._clock = _clock or (lambda: datetime.now(timezone.utc))
        self._lock_backend = _lock_backend or _platform_lock_backend()
        self._thread_lock = threading.Lock()

    def persist_grant(self, grant: ConfirmationGrant) -> ConfirmationAuditRecord:
        evaluated_at = self._now()
        request_id = (
            grant.confirmation_request_id if type(grant) is ConfirmationGrant else None
        )
        if type(grant) is not ConfirmationGrant or grant.consumed_at is not None:
            return self._blocked(
                BlockerCode.CONFIRMATION_INVALID,
                evaluated_at,
                request_id=request_id,
            )
        try:
            with self._exclusive_lock():
                if self._path.exists():
                    return self._blocked(
                        BlockerCode.CONFIRMATION_INVALID,
                        evaluated_at,
                        request_id=request_id,
                    )
                self._atomic_write(self._state_payload(grant))
        except (OSError, _StorageFailure):
            return self._blocked(
                BlockerCode.CONFIRMATION_STORAGE_BLOCKER,
                evaluated_at,
                request_id=request_id,
            )
        return ConfirmationAuditRecord(
            confirmation_request_id=request_id,
            outcome="SUCCESS",
            blocker_code=None,
            evaluated_at=evaluated_at,
            consumed_at=None,
        )

    def validate_and_consume(
        self,
        confirmation_token: str,
        expected_config_hash: str,
        expected_data_plan_hash: str,
        expected_assumptions_hash: str,
    ) -> ConfirmationAuditRecord:
        evaluated_at = self._now()
        try:
            with self._exclusive_lock():
                try:
                    grant_payload = self._read_grant_payload()
                except _InvalidState:
                    return self._blocked(
                        BlockerCode.CONFIRMATION_INVALID,
                        evaluated_at,
                    )

                request_id = grant_payload["confirmation_request_id"]
                consumed_at = grant_payload["consumed_at"]
                if consumed_at is not None:
                    return self._blocked(
                        BlockerCode.CONFIRMATION_ALREADY_USED,
                        evaluated_at,
                        request_id=request_id,
                        consumed_at=consumed_at,
                    )
                if grant_payload["single_use"] is not True:
                    return self._blocked(
                        BlockerCode.CONFIRMATION_INVALID,
                        evaluated_at,
                        request_id=request_id,
                    )
                grant = ConfirmationGrant(**grant_payload)

                now = _utc_datetime(evaluated_at, "evaluated_at")
                expires = _utc_datetime(grant.expires_at, "grant.expires_at")
                if now >= expires:
                    return self._blocked(
                        BlockerCode.CONFIRMATION_EXPIRED,
                        evaluated_at,
                        request_id=grant.confirmation_request_id,
                    )
                if type(confirmation_token) is not str or not confirmation_token:
                    return self._blocked(
                        BlockerCode.CONFIRMATION_REQUIRED,
                        evaluated_at,
                        request_id=grant.confirmation_request_id,
                    )
                supplied_token_hash = sha256_bytes(confirmation_token.encode("utf-8"))
                if not hmac.compare_digest(
                    supplied_token_hash,
                    grant.confirmation_token_hash,
                ):
                    return self._blocked(
                        BlockerCode.CONFIRMATION_HASH_MISMATCH,
                        evaluated_at,
                        request_id=grant.confirmation_request_id,
                    )
                expected_hashes = (
                    expected_config_hash,
                    expected_data_plan_hash,
                    expected_assumptions_hash,
                )
                stored_hashes = (
                    grant.bound_config_hash,
                    grant.bound_data_plan_hash,
                    grant.bound_assumptions_hash,
                )
                if any(
                    type(expected) is not str
                    or not _SHA256_HEX.fullmatch(expected)
                    or not hmac.compare_digest(expected, stored)
                    for expected, stored in zip(expected_hashes, stored_hashes, strict=True)
                ):
                    return self._blocked(
                        BlockerCode.CONFIRMATION_HASH_MISMATCH,
                        evaluated_at,
                        request_id=grant.confirmation_request_id,
                    )

                consumed = replace(grant, consumed_at=evaluated_at)
                self._atomic_write(self._state_payload(consumed))
        except (OSError, _StorageFailure):
            return self._blocked(
                BlockerCode.CONFIRMATION_STORAGE_BLOCKER,
                evaluated_at,
            )
        return ConfirmationAuditRecord(
            confirmation_request_id=consumed.confirmation_request_id,
            outcome="SUCCESS",
            blocker_code=None,
            evaluated_at=evaluated_at,
            consumed_at=evaluated_at,
        )

    def _now(self) -> str:
        value = self._clock()
        if type(value) is not datetime:
            raise ValueError("clock: datetime required")
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("clock: UTC datetime required")
        return value.isoformat()

    @contextmanager
    def _exclusive_lock(self):
        if not self._thread_lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS):
            raise _StorageFailure
        try:
            with self._lock_path.open("a+b") as handle:
                acquired = False
                try:
                    self._lock_backend.acquire(handle)
                    acquired = True
                    yield
                finally:
                    if acquired:
                        self._lock_backend.release(handle)
        finally:
            self._thread_lock.release()

    def _read_grant_payload(self) -> dict[str, object]:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise _InvalidState from exc
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise _InvalidState from exc
        if type(payload) is not dict or set(payload) != _CONFIRMATION_STATE_FIELDS:
            raise _InvalidState
        if (
            payload["schema_version"] != _CONFIRMATION_STATE_SCHEMA
            or payload["state_version"] != _CONFIRMATION_STATE_VERSION
        ):
            raise _InvalidState
        grant_payload = payload["grant"]
        if type(grant_payload) is not dict or set(grant_payload) != _GRANT_STATE_FIELDS:
            raise _InvalidState
        try:
            _stable_identifier(
                grant_payload["confirmation_request_id"],
                "confirmation_request_id",
            )
            _sha256(grant_payload["confirmation_token_hash"], "confirmation_token_hash")
            _sha256(grant_payload["bound_config_hash"], "bound_config_hash")
            _sha256(grant_payload["bound_data_plan_hash"], "bound_data_plan_hash")
            _sha256(grant_payload["bound_assumptions_hash"], "bound_assumptions_hash")
            issued = _utc_datetime(grant_payload["issued_at"], "issued_at")
            expires = _utc_datetime(grant_payload["expires_at"], "expires_at")
            if expires <= issued:
                raise ValueError
            if type(grant_payload["single_use"]) is not bool:
                raise ValueError
            consumed_at = grant_payload["consumed_at"]
            if consumed_at is not None:
                consumed = _utc_datetime(consumed_at, "consumed_at")
                if consumed < issued:
                    raise ValueError
        except (TypeError, ValueError) as exc:
            raise _InvalidState from exc
        return grant_payload

    def _state_payload(self, grant: ConfirmationGrant) -> dict[str, object]:
        return {
            "schema_version": _CONFIRMATION_STATE_SCHEMA,
            "state_version": _CONFIRMATION_STATE_VERSION,
            "grant": asdict(grant),
        }

    def _atomic_write(self, payload: Mapping[str, object]) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                serialized = json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                handle.write(serialized)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
            self._fsync_directory()
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _fsync_directory(self) -> None:
        if os.name != "posix":
            return
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(self._path.parent, flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _blocked(
        code: BlockerCode,
        evaluated_at: str,
        *,
        request_id: str | None = None,
        consumed_at: str | None = None,
    ) -> ConfirmationAuditRecord:
        return ConfirmationAuditRecord(
            confirmation_request_id=request_id,
            outcome="BLOCKED",
            blocker_code=code,
            evaluated_at=evaluated_at,
            consumed_at=consumed_at,
        )


@dataclass(frozen=True, slots=True)
class _ConfirmationHandoff:
    grant: ConfirmationGrant
    confirmation_token: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.grant) is not ConfirmationGrant:
            raise ValueError("ConfirmationGrant required")
        _string(self.confirmation_token, "confirmation_token")


def _dataset_summary(requirement: DatasetRequirement) -> Mapping[str, object]:
    return MappingProxyType(
        {
            "dataset_role": requirement.dataset_role,
            "provider_preference": requirement.provider_preference,
            "symbol": requirement.symbol,
            "market": requirement.market,
            "timeframe": requirement.timeframe,
            "requested_start": requirement.requested_start,
            "requested_end": requirement.requested_end,
            "warmup_bars": requirement.warmup_bars,
            "adjustment_requirement": requirement.adjustment_requirement,
            "corporate_action_requirement": requirement.corporate_action_requirement,
            "cost_profile_requirement": requirement.cost_profile_requirement,
            "capability_requirements": requirement.capability_requirements,
        }
    )


def _validate_contract_binding(
    ir: NormalizedStrategyIR,
    plan: DataPlan,
    assumptions: ExecutionAssumptions,
) -> None:
    if (
        ir.schema_version != "v2.1"
        or plan.schema_version != ir.schema_version
        or assumptions.schema_version != ir.schema_version
    ):
        raise ValueError("schema_version: matching v2.1 contracts required")
    if (
        plan.primary.symbol != ir.symbol
        or plan.primary.market != ir.market
        or plan.primary.timeframe != ir.timeframe
    ):
        raise ValueError("DataPlan does not match NormalizedStrategyIR")
    if (
        assumptions.fill_timing != ir.fill_timing
        or assumptions.report_language != ir.report_language
        or assumptions.session_policy != ir.session
    ):
        raise ValueError("ExecutionAssumptions do not match NormalizedStrategyIR")
    if plan.primary.cost_profile_requirement != assumptions.cost_profile_id:
        raise ValueError("DataPlan cost profile does not match ExecutionAssumptions")


def create_confirmation_request(
    ir: NormalizedStrategyIR,
    data_plan: DataPlan,
    assumptions: ExecutionAssumptions,
    generated_at: str,
    expires_at: str,
) -> ConfirmationRequest:
    """Create a typed request whose three binding hashes come from their owners."""
    if type(ir) is not NormalizedStrategyIR:
        raise ValueError("NormalizedStrategyIR required")
    if type(data_plan) is not DataPlan:
        raise ValueError("DataPlan required")
    if type(assumptions) is not ExecutionAssumptions:
        raise ValueError("ExecutionAssumptions required")
    _validate_contract_binding(ir, data_plan, assumptions)

    config_digest = normalized_config_hash(ir)
    plan_digest = compute_data_plan_hash(data_plan)
    assumptions_digest = assumptions_hash(assumptions)
    generated = _utc_datetime(generated_at, "generated_at")
    expires = _utc_datetime(expires_at, "expires_at")
    if expires <= generated:
        raise ValueError("expires_at: must be after generated_at")
    request_fields = {
        "schema_version": ir.schema_version,
        "normalized_config_hash": config_digest,
        "data_plan_hash": plan_digest,
        "assumptions_hash": assumptions_digest,
        "config_summary": {
            "strategy_id": ir.strategy_id,
            "strategy_family": ir.strategy_family,
            "strategy_name": ir.strategy_name,
            "symbol": ir.symbol,
            "market": ir.market,
            "timeframe": ir.timeframe,
            "fill_timing": ir.fill_timing,
            "optimization_allowed": ir.optimization_allowed,
            "report_language": ir.report_language,
        },
        "data_plan_summary": {
            "primary": _dataset_summary(data_plan.primary),
            "auxiliary": tuple(_dataset_summary(item) for item in data_plan.auxiliary),
            "requested_range": data_plan.requested_range,
        },
        "cost_profile_id": assumptions.cost_profile_id,
        "corporate_action_profile_id": assumptions.corporate_action_profile_id,
        "generated_at": generated_at,
        "expires_at": expires_at,
    }
    return ConfirmationRequest(
        confirmation_request_id=_confirmation_request_id(request_fields),
        **request_fields,
    )


def issue_confirmation_grant(
    request: ConfirmationRequest,
    approval: ApprovalRecord,
    issued_at: str,
) -> _ConfirmationHandoff:
    """Issue hash-only grant state plus one private, successful plaintext handoff."""
    if type(request) is not ConfirmationRequest:
        raise ValueError("ConfirmationRequest required")
    if request.confirmation_request_id != _confirmation_request_id(_request_id_fields(request)):
        raise ValueError("request integrity does not match confirmation_request_id")
    if type(approval) is not ApprovalRecord:
        raise ValueError("ApprovalRecord required")
    if approval.decision != "CONFIRMED_EXECUTE":
        raise ValueError("approval decision must equal CONFIRMED_EXECUTE")
    if approval.confirmation_request_id != request.confirmation_request_id:
        raise ValueError("approval request binding does not match")

    generated = _utc_datetime(request.generated_at, "request.generated_at")
    recorded = _utc_datetime(approval.recorded_at_utc, "approval.recorded_at_utc")
    issued = _utc_datetime(issued_at, "issued_at")
    expires = _utc_datetime(request.expires_at, "request.expires_at")
    if recorded < generated or recorded > issued:
        raise ValueError("approval time must fall within request and issue times")
    if issued < generated or issued >= expires:
        raise ValueError("issued_at must be before request expiry")

    token = secrets.token_urlsafe(32)
    grant = ConfirmationGrant(
        confirmation_request_id=request.confirmation_request_id,
        confirmation_token_hash=sha256_bytes(token.encode("utf-8")),
        bound_config_hash=request.normalized_config_hash,
        bound_data_plan_hash=request.data_plan_hash,
        bound_assumptions_hash=request.assumptions_hash,
        issued_at=issued_at,
        expires_at=request.expires_at,
        single_use=True,
        consumed_at=None,
    )
    return _ConfirmationHandoff(grant=grant, confirmation_token=token)


def validate_and_consume(
    confirmation_token: str,
    expected_config_hash: str,
    expected_data_plan_hash: str,
    expected_assumptions_hash: str,
    store: ConfirmationStore,
) -> ConfirmationAuditRecord:
    """Delegate one-time validation and consumption to the configured store."""
    return store.validate_and_consume(
        confirmation_token,
        expected_config_hash,
        expected_data_plan_hash,
        expected_assumptions_hash,
    )


__all__ = (
    "ApprovalRecord",
    "ConfirmationAuditRecord",
    "ConfirmationGrant",
    "ConfirmationRequest",
    "ConfirmationStore",
    "FileConfirmationStore",
    "create_confirmation_request",
    "issue_confirmation_grant",
    "validate_and_consume",
)
