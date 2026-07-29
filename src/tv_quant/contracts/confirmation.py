"""Typed V2.1 confirmation request, grant state, and one-time token handoff."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
import secrets
from types import MappingProxyType

from tv_quant.run_manifest import canonical_hash, sha256_bytes

from .data_plan import DataPlan, DatasetRequirement, data_plan_hash as compute_data_plan_hash
from .execution_assumptions import ExecutionAssumptions, assumptions_hash
from .normalized_ir import NormalizedStrategyIR, normalized_config_hash


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
    request_id = "confirmation-request-" + canonical_hash(
        {
            "schema_version": ir.schema_version,
            "normalized_config_hash": config_digest,
            "data_plan_hash": plan_digest,
            "assumptions_hash": assumptions_digest,
            "generated_at": generated_at,
            "expires_at": expires_at,
        }
    )

    return ConfirmationRequest(
        confirmation_request_id=request_id,
        schema_version=ir.schema_version,
        normalized_config_hash=config_digest,
        data_plan_hash=plan_digest,
        assumptions_hash=assumptions_digest,
        config_summary={
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
        data_plan_summary={
            "primary": _dataset_summary(data_plan.primary),
            "auxiliary": tuple(_dataset_summary(item) for item in data_plan.auxiliary),
            "requested_range": data_plan.requested_range,
        },
        cost_profile_id=assumptions.cost_profile_id,
        corporate_action_profile_id=assumptions.corporate_action_profile_id,
        generated_at=generated_at,
        expires_at=expires_at,
    )


def issue_confirmation_grant(
    request: ConfirmationRequest,
    approval: ApprovalRecord,
    issued_at: str,
) -> _ConfirmationHandoff:
    """Issue hash-only grant state plus one private, successful plaintext handoff."""
    if type(request) is not ConfirmationRequest:
        raise ValueError("ConfirmationRequest required")
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


__all__ = (
    "ApprovalRecord",
    "ConfirmationGrant",
    "ConfirmationRequest",
    "create_confirmation_request",
    "issue_confirmation_grant",
)
