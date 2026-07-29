"""Tests for the typed V2.1 confirmation request and grant boundary."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, asdict, replace
import inspect
import json

import pytest

from tv_quant.contracts.confirmation import (
    ApprovalRecord,
    ConfirmationGrant,
    ConfirmationRequest,
    create_confirmation_request,
    issue_confirmation_grant,
)
from tv_quant.contracts.data_plan import build_data_plan, data_plan_hash
from tv_quant.contracts.execution_assumptions import (
    assumptions_hash,
    build_execution_assumptions,
)
from tv_quant.contracts.normalized_ir import normalize_strategy_spec, normalized_config_hash
from tv_quant.contracts.strategy_v2 import validate_strategy_mapping_v2
from tv_quant.run_manifest import sha256_bytes


GENERATED_AT = "2026-07-29T01:00:00+00:00"
RECORDED_AT = "2026-07-29T01:01:00+00:00"
ISSUED_AT = "2026-07-29T01:02:00+00:00"
EXPIRES_AT = "2026-07-29T01:15:00+00:00"


class _ValidationRegistry:
    def validate_strategy(self, _spec: object) -> tuple[object, ...]:
        return ()


def _strategy_mapping() -> dict[str, object]:
    price = {"node_type": "price_ref", "field": "close", "unit": "USD"}
    ema = {
        "node_type": "indicator_ref",
        "name": "EMA",
        "parameters": {"period": 50},
        "output": "series",
        "unit": "USD",
    }
    return {
        "schema_version": "v2.1",
        "strategy_id": "ema-cross-spy",
        "strategy_family": "ema_crossover",
        "strategy_name": "SPY EMA crossover",
        "symbol": "SPY",
        "market": "US_EQUITY",
        "timeframe": "1d",
        "session": {
            "timezone": "America/New_York",
            "regular_hours_only": True,
            "calendar_id": "XNYS",
        },
        "backtest_range": {"start": "2024-01-02", "end": "2024-12-31"},
        "initial_capital": {"amount": 100000, "currency": "USD"},
        "entry": {"node_type": "compare", "operator": "gt", "left": price, "right": ema},
        "exit": {"node_type": "compare", "operator": "lt", "left": price, "right": ema},
        "filters": [],
        "position_sizing": {"type": "fixed_fraction", "fraction": "1"},
        "stop": {"enabled": False},
        "target": {"enabled": False},
        "fill_timing": "next_bar_open",
        "data": {"source": "validated_local_cache_first", "cost_profile": "cost.bps.v1"},
        "benchmark": {"type": "buy_and_hold", "symbol": "same_as_strategy"},
        "plugin": None,
        "optimization_allowed": False,
        "report_language": "zh-CN",
    }


def _contracts():
    result = normalize_strategy_spec(
        validate_strategy_mapping_v2(_strategy_mapping()),
        capability_registry=_ValidationRegistry(),
        source_config_hash="source-config-hash",
    )
    assert result.ir is not None
    ir = result.ir
    plan = build_data_plan(ir, object())
    assumptions = build_execution_assumptions(
        ir,
        plan,
        {
            "cost_profile_id": "cost.bps.v1",
            "corporate_action_profile_id": "corporate-actions.v1",
            "benchmark_protocol_id": "buy-and-hold.v1",
            "benchmark_protocol_version": "v1",
            "capability_snapshot_hash": "a" * 64,
            "normalizer_version": "v2.1",
        },
    )
    return ir, plan, assumptions


def _request() -> ConfirmationRequest:
    return create_confirmation_request(*_contracts(), GENERATED_AT, EXPIRES_AT)


def _approval(request: ConfirmationRequest) -> ApprovalRecord:
    return ApprovalRecord(
        approval_id="approval-001",
        confirmation_request_id=request.confirmation_request_id,
        decision="CONFIRMED_EXECUTE",
        recorded_at_utc=RECORDED_AT,
        actor="dialogue.user",
    )


def test_request_contains_three_binding_hashes_and_summaries() -> None:
    ir, plan, assumptions = _contracts()
    request = create_confirmation_request(ir, plan, assumptions, GENERATED_AT, EXPIRES_AT)

    assert request.normalized_config_hash == normalized_config_hash(ir)
    assert request.data_plan_hash == data_plan_hash(plan)
    assert request.assumptions_hash == assumptions_hash(assumptions)
    assert request.config_summary["strategy_id"] == ir.strategy_id
    assert request.config_summary["symbol"] == "SPY"
    assert request.data_plan_summary["primary"]["symbol"] == "SPY"
    assert request.data_plan_summary["requested_range"] == plan.requested_range
    assert request.cost_profile_id == assumptions.cost_profile_id
    assert request.corporate_action_profile_id == assumptions.corporate_action_profile_id


def test_request_binds_formal_execution_assumptions_hash() -> None:
    ir, plan, assumptions = _contracts()
    request = create_confirmation_request(ir, plan, assumptions, GENERATED_AT, EXPIRES_AT)
    changed = replace(assumptions, benchmark_protocol_version="v2")

    assert request.assumptions_hash == assumptions_hash(assumptions)
    assert request.assumptions_hash != assumptions_hash(changed)
    with pytest.raises(ValueError, match="ExecutionAssumptions required"):
        create_confirmation_request(ir, plan, {}, GENERATED_AT, EXPIRES_AT)  # type: ignore[arg-type]


def test_grant_requires_typed_confirmed_execute(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    approval = _approval(request)
    monkeypatch.setattr(
        "tv_quant.contracts.confirmation.secrets.token_urlsafe",
        lambda size: "typed-approval-token" if size == 32 else pytest.fail("wrong token size"),
    )

    handoff = issue_confirmation_grant(request, approval, ISSUED_AT)

    assert handoff.grant.confirmation_request_id == request.confirmation_request_id
    assert handoff.confirmation_token == "typed-approval-token"
    with pytest.raises(ValueError, match="CONFIRMED_EXECUTE"):
        replace(approval, decision="APPROVE")
    with pytest.raises(ValueError, match="ApprovalRecord required"):
        issue_confirmation_grant(request, {"decision": "CONFIRMED_EXECUTE"}, ISSUED_AT)  # type: ignore[arg-type]


def test_token_is_random_and_state_has_only_token_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    approval = _approval(request)
    tokens = iter(("first-plaintext-token", "second-plaintext-token"))
    sizes: list[int] = []

    def _token_urlsafe(size: int) -> str:
        sizes.append(size)
        return next(tokens)

    monkeypatch.setattr("tv_quant.contracts.confirmation.secrets.token_urlsafe", _token_urlsafe)
    first = issue_confirmation_grant(request, approval, ISSUED_AT)
    second = issue_confirmation_grant(request, approval, ISSUED_AT)

    assert sizes == [32, 32]
    assert first.confirmation_token != second.confirmation_token
    assert first.grant.confirmation_token_hash == sha256_bytes(b"first-plaintext-token")
    assert second.grant.confirmation_token_hash == sha256_bytes(b"second-plaintext-token")
    assert "confirmation_token" not in asdict(first.grant)
    assert "first-plaintext-token" not in json.dumps(asdict(first.grant), sort_keys=True)
    assert "first-plaintext-token" not in repr(first)
    assert "token" not in inspect.signature(issue_confirmation_grant).parameters


def test_expiry_and_single_use_fields_are_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    monkeypatch.setattr(
        "tv_quant.contracts.confirmation.secrets.token_urlsafe", lambda _size: "one-time-token"
    )
    handoff = issue_confirmation_grant(request, _approval(request), ISSUED_AT)
    grant = handoff.grant

    assert request.generated_at == GENERATED_AT
    assert request.expires_at == EXPIRES_AT
    assert grant.issued_at == ISSUED_AT
    assert grant.expires_at == EXPIRES_AT
    assert grant.single_use is True
    assert grant.consumed_at is None
    with pytest.raises(FrozenInstanceError):
        grant.single_use = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        request.config_summary = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        request.config_summary["symbol"] = "QQQ"  # type: ignore[index]


def test_chat_text_is_not_accepted_as_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    request = _request()
    monkeypatch.setattr(
        "tv_quant.contracts.confirmation.secrets.token_urlsafe",
        lambda _size: pytest.fail("chat text must fail before token generation"),
    )

    for chat_text in ("approved", "CONFIRMED_EXECUTE", "批准"):
        with pytest.raises(ValueError, match="ApprovalRecord required"):
            issue_confirmation_grant(request, chat_text, ISSUED_AT)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("generated_at", "expires_at", "message"),
    (
        ("2026-07-29T01:00:00", EXPIRES_AT, "UTC"),
        ("2026-07-29T09:00:00+08:00", EXPIRES_AT, "UTC"),
        (GENERATED_AT, GENERATED_AT, "after generated_at"),
    ),
)
def test_request_rejects_invalid_utc_or_expiry_order(
    generated_at: str, expires_at: str, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        create_confirmation_request(*_contracts(), generated_at, expires_at)


def test_grant_rejects_wrong_request_expired_issue_and_untyped_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    approval = _approval(request)
    monkeypatch.setattr(
        "tv_quant.contracts.confirmation.secrets.token_urlsafe",
        lambda _size: pytest.fail("invalid inputs must fail before token generation"),
    )

    with pytest.raises(ValueError, match="request binding"):
        issue_confirmation_grant(
            request,
            replace(approval, confirmation_request_id="different-request"),
            ISSUED_AT,
        )
    with pytest.raises(ValueError, match="before request expiry"):
        issue_confirmation_grant(request, approval, EXPIRES_AT)
    with pytest.raises(ValueError, match="ConfirmationRequest required"):
        issue_confirmation_grant(  # type: ignore[arg-type]
            {"confirmation_request_id": request.confirmation_request_id},
            approval,
            ISSUED_AT,
        )


def test_request_hashes_change_with_each_bound_contract() -> None:
    ir, plan, assumptions = _contracts()
    baseline = create_confirmation_request(ir, plan, assumptions, GENERATED_AT, EXPIRES_AT)

    changed_ir = replace(ir, strategy_name="Changed name")
    assert create_confirmation_request(
        changed_ir, plan, assumptions, GENERATED_AT, EXPIRES_AT
    ).normalized_config_hash != baseline.normalized_config_hash

    changed_plan = replace(plan, requested_range={"start": "2023-01-02", "end": "2024-12-31"})
    assert create_confirmation_request(
        ir, changed_plan, assumptions, GENERATED_AT, EXPIRES_AT
    ).data_plan_hash != baseline.data_plan_hash

    changed_assumptions = replace(assumptions, benchmark_protocol_version="v2")
    assert create_confirmation_request(
        ir, plan, changed_assumptions, GENERATED_AT, EXPIRES_AT
    ).assumptions_hash != baseline.assumptions_hash


def test_public_contracts_are_frozen_slotted_and_grant_state_is_serializable() -> None:
    request = _request()
    approval = _approval(request)
    grant = ConfirmationGrant(
        confirmation_request_id=request.confirmation_request_id,
        confirmation_token_hash="b" * 64,
        bound_config_hash=request.normalized_config_hash,
        bound_data_plan_hash=request.data_plan_hash,
        bound_assumptions_hash=request.assumptions_hash,
        issued_at=ISSUED_AT,
        expires_at=EXPIRES_AT,
        single_use=True,
        consumed_at=None,
    )

    assert not hasattr(request, "__dict__")
    assert not hasattr(approval, "__dict__")
    assert not hasattr(grant, "__dict__")
    assert json.loads(json.dumps(asdict(grant)))["confirmation_token_hash"] == "b" * 64


def test_callable_string_subclasses_are_rejected_from_frozen_fields() -> None:
    class _CallableString(str):
        def __call__(self) -> None:
            return None

    request = _request()
    with pytest.raises(ValueError, match="non-empty string required"):
        replace(_approval(request), decision=_CallableString("CONFIRMED_EXECUTE"))
    with pytest.raises(ValueError, match="non-empty string required"):
        replace(request, schema_version=_CallableString("v2.1"))


def test_request_rejects_data_plan_cost_profile_mismatch() -> None:
    ir, plan, assumptions = _contracts()
    mismatched_plan = replace(
        plan,
        primary=replace(plan.primary, cost_profile_requirement="different.cost.v1"),
    )

    with pytest.raises(ValueError, match="cost profile"):
        create_confirmation_request(
            ir,
            mismatched_plan,
            assumptions,
            GENERATED_AT,
            EXPIRES_AT,
        )


@pytest.mark.parametrize(
    "field",
    (
        "normalized_config_hash",
        "data_plan_hash",
        "assumptions_hash",
        "config_summary",
        "data_plan_summary",
        "cost_profile_id",
        "corporate_action_profile_id",
        "generated_at",
        "expires_at",
    ),
)
def test_grant_rejects_tampered_typed_request_before_token_generation(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing any approval-visible request field must invalidate its approved ID."""
    request = _request()
    changed_config_summary = dict(request.config_summary)
    changed_config_summary["strategy_name"] = "Tampered strategy"
    changed_data_plan_summary = dict(request.data_plan_summary)
    changed_data_plan_summary["requested_range"] = {
        "start": "2023-01-02",
        "end": "2024-12-31",
    }
    replacements: dict[str, object] = {
        "normalized_config_hash": "b" * 64,
        "data_plan_hash": "c" * 64,
        "assumptions_hash": "d" * 64,
        "config_summary": changed_config_summary,
        "data_plan_summary": changed_data_plan_summary,
        "cost_profile_id": "different.cost.v1",
        "corporate_action_profile_id": "different-actions.v1",
        "generated_at": "2026-07-29T00:59:00+00:00",
        "expires_at": "2026-07-29T01:30:00+00:00",
    }
    tampered = replace(request, **{field: replacements[field]})
    approval = _approval(request)
    monkeypatch.setattr(
        "tv_quant.contracts.confirmation.secrets.token_urlsafe",
        lambda _size: pytest.fail(f"token generation reached for tampered {field}"),
    )

    with pytest.raises(ValueError, match="request integrity"):
        issue_confirmation_grant(tampered, approval, ISSUED_AT)
