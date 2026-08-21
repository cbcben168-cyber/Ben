"""Fixed S0-S10 aggregation contracts for evaluated universe candidates."""

from __future__ import annotations

import ast
from dataclasses import replace
import inspect

import pytest

from tv_quant.pattern_finder.universe_foundation import Decision, FieldDecision, SecurityEvaluation
from tv_quant.pattern_finder.universe_foundation import funnel as funnel_module
from tv_quant.pattern_finder.universe_foundation.funnel import (
    FunnelStage,
    UniverseFunnel,
    build_funnel,
    funnel_sha256,
)


STAGE_IDS = (
    "S1_IDENTITY_VALID",
    "S2_EXCHANGE_ALLOWED",
    "S3_SECURITY_CLASS_ALLOWED",
    "S4_ACTIVE_STATUS_ALLOWED",
    "S5_PRICE_ALLOWED",
    "S6_MARKET_CAP_ALLOWED",
    "S7_SECTOR_INDUSTRY_ALLOWED",
    "S8_LISTING_HISTORY_ALLOWED",
    "S9_LIQUIDITY_ALLOWED",
)


def _evaluation(
    symbol: str,
    *,
    stock_id: str | None = None,
    futu_code: str | None = None,
    changes: dict[str, tuple[Decision, str]] | None = None,
) -> SecurityEvaluation:
    changes = changes or {}
    decisions = tuple(
        FieldDecision(
            field_id=stage_id,
            raw_value="existing Task 6 value",
            normalized_value="existing Task 6 value",
            operator=None,
            threshold=None,
            decision=changes.get(stage_id, (Decision.PASS, f"{stage_id}_PASS"))[0],
            reason_code=changes.get(stage_id, (Decision.PASS, f"{stage_id}_PASS"))[1],
            evidence_source="TASK_6",
            evidence_observed_at_utc=None,
            evidence_version="task-6/v1",
            evidence_references=(),
        )
        for stage_id in STAGE_IDS
    )
    first = next((item for item in decisions if item.decision is not Decision.PASS), None)
    return SecurityEvaluation(
        stock_id=stock_id or f"stock-{symbol}",
        futu_code=futu_code or f"US.{symbol}",
        symbol=symbol,
        name=f"{symbol} Inc.",
        field_decisions=decisions,
        first_exit_stage=None if first is None else first.field_id,
        first_exit_reason_code=None if first is None else first.reason_code,
        is_member=first is None,
        is_quarantined=any(item.decision is Decision.UNKNOWN for item in decisions),
    )


@pytest.fixture
def evaluations() -> tuple[SecurityEvaluation, ...]:
    return (
        _evaluation("AAPL"),
        _evaluation("MSFT", changes={"S2_EXCHANGE_ALLOWED": (Decision.FAIL, "EXCHANGE_NOT_ALLOWED")}),
        _evaluation("NVDA", changes={"S4_ACTIVE_STATUS_ALLOWED": (Decision.UNKNOWN, "ACTIVE_STATUS_UNKNOWN")}),
        _evaluation("TSLA", changes={"S9_LIQUIDITY_ALLOWED": (Decision.FAIL, "LIQUIDITY_BELOW_MINIMUM")}),
    )


def _stage(funnel: UniverseFunnel, stage_id: str) -> FunnelStage:
    return next(stage for stage in funnel.stages if stage.stage_id == stage_id)


def test_fixed_s0_s10_counts_reconcile_and_s10_is_members(
    evaluations: tuple[SecurityEvaluation, ...],
) -> None:
    funnel = build_funnel(evaluations)

    assert tuple(stage.stage_id for stage in funnel.stages) == (
        "S0_DISCOVERED_US_CASH_SECURITIES",
        *STAGE_IDS,
        "S10_CORE_UNIVERSE",
    )
    assert all(stage.input_count == stage.pass_count + stage.fail_count + stage.unknown_count for stage in funnel.stages)
    assert all(stage.output_count == stage.pass_count for stage in funnel.stages)
    assert all(
        funnel.stages[index + 1].input_count == stage.pass_count
        for index, stage in enumerate(funnel.stages[:-1])
    )
    assert _stage(funnel, "S0_DISCOVERED_US_CASH_SECURITIES") == FunnelStage(
        stage_order=0,
        stage_id="S0_DISCOVERED_US_CASH_SECURITIES",
        input_count=4,
        pass_count=4,
        fail_count=0,
        unknown_count=0,
        reason_counts=(),
        output_count=4,
    )
    assert _stage(funnel, "S2_EXCHANGE_ALLOWED").reason_counts == (
        ("EXCHANGE_NOT_ALLOWED", 1),
        ("S2_EXCHANGE_ALLOWED_PASS", 3),
    )
    assert _stage(funnel, "S4_ACTIVE_STATUS_ALLOWED").reason_counts == (
        ("ACTIVE_STATUS_UNKNOWN", 1),
        ("S4_ACTIVE_STATUS_ALLOWED_PASS", 2),
    )
    assert _stage(funnel, "S9_LIQUIDITY_ALLOWED").reason_counts == (
        ("LIQUIDITY_BELOW_MINIMUM", 1),
        ("S9_LIQUIDITY_ALLOWED_PASS", 1),
    )
    assert _stage(funnel, "S10_CORE_UNIVERSE").pass_count == 1
    assert _stage(funnel, "S10_CORE_UNIVERSE").pass_count == len(funnel.members)
    assert tuple(member.symbol for member in funnel.members) == ("AAPL",)
    assert tuple(item.symbol for item in funnel.evaluations) == ("AAPL", "MSFT", "NVDA", "TSLA")


def test_fail_and_unknown_are_first_exit_only_and_unknown_is_not_fail() -> None:
    failed = _evaluation(
        "FAIL",
        changes={
            "S2_EXCHANGE_ALLOWED": (Decision.FAIL, "EXCHANGE_NOT_ALLOWED"),
            "S3_SECURITY_CLASS_ALLOWED": (Decision.UNKNOWN, "CLASSIFICATION_UNKNOWN"),
        },
    )
    unknown = _evaluation(
        "UNKNOWN",
        changes={"S2_EXCHANGE_ALLOWED": (Decision.UNKNOWN, "EXCHANGE_UNKNOWN")},
    )

    funnel = build_funnel((failed, unknown))

    assert _stage(funnel, "S2_EXCHANGE_ALLOWED").fail_count == 1
    assert _stage(funnel, "S2_EXCHANGE_ALLOWED").unknown_count == 1
    assert _stage(funnel, "S3_SECURITY_CLASS_ALLOWED").input_count == 0
    assert _stage(funnel, "S3_SECURITY_CLASS_ALLOWED").unknown_count == 0
    assert {item.symbol: item.first_exit_stage for item in funnel.evaluations} == {
        "FAIL": "S2_EXCHANGE_ALLOWED",
        "UNKNOWN": "S2_EXCHANGE_ALLOWED",
    }


def test_reason_counts_hash_and_content_are_shuffle_stable(
    evaluations: tuple[SecurityEvaluation, ...],
) -> None:
    forward = build_funnel(evaluations)
    shuffled = build_funnel(tuple(reversed(evaluations)))
    changed_reason = build_funnel(
        (
            replace(
                evaluations[0],
                field_decisions=tuple(
                    replace(item, reason_code="S1_AUDIT_REASON_CHANGED")
                    if item.field_id == "S1_IDENTITY_VALID"
                    else item
                    for item in evaluations[0].field_decisions
                ),
            ),
            *evaluations[1:],
        )
    )
    changed_audit_value = build_funnel(
        (
            replace(
                evaluations[0],
                field_decisions=tuple(
                    replace(item, raw_value="changed source value", evidence_source="CHANGED_TASK_6")
                    if item.field_id == "S1_IDENTITY_VALID"
                    else item
                    for item in evaluations[0].field_decisions
                ),
            ),
            *evaluations[1:],
        )
    )

    assert forward == shuffled
    assert funnel_sha256(forward) == funnel_sha256(shuffled)
    assert funnel_sha256(forward) != funnel_sha256(changed_reason)
    assert funnel_sha256(forward) != funnel_sha256(changed_audit_value)


def test_duplicate_or_missing_candidate_inputs_fail_closed(
    evaluations: tuple[SecurityEvaluation, ...],
) -> None:
    with pytest.raises(ValueError, match="evaluations: non-empty"):
        build_funnel(())
    with pytest.raises(ValueError, match="duplicate evaluation key"):
        build_funnel((evaluations[0], evaluations[0]))
    with pytest.raises(ValueError, match="UNIVERSE_IDENTITY_BLOCKER"):
        build_funnel((evaluations[0], replace(evaluations[1], futu_code=evaluations[0].futu_code)))
    with pytest.raises(ValueError, match="UNIVERSE_IDENTITY_BLOCKER"):
        build_funnel((evaluations[0], replace(evaluations[1], stock_id=evaluations[0].stock_id)))


def test_identity_blocker_rows_are_preserved_not_deduplicated() -> None:
    first = _evaluation(
        "ALPHA",
        stock_id="same-stock",
        futu_code="US.ALPHA",
        changes={"S1_IDENTITY_VALID": (Decision.UNKNOWN, "UNIVERSE_IDENTITY_BLOCKER")},
    )
    second = _evaluation(
        "BETA",
        stock_id="same-stock",
        futu_code="US.BETA",
        changes={"S1_IDENTITY_VALID": (Decision.UNKNOWN, "UNIVERSE_IDENTITY_BLOCKER")},
    )

    funnel = build_funnel((second, first))

    assert tuple(item.futu_code for item in funnel.evaluations) == ("US.ALPHA", "US.BETA")
    assert _stage(funnel, "S1_IDENTITY_VALID").unknown_count == 2
    assert _stage(funnel, "S1_IDENTITY_VALID").reason_counts == (("UNIVERSE_IDENTITY_BLOCKER", 2),)


def test_public_funnel_value_objects_reject_fabricated_reconciliation(
    evaluations: tuple[SecurityEvaluation, ...],
) -> None:
    funnel = build_funnel(evaluations)

    with pytest.raises(ValueError, match="reason_counts must reconcile"):
        FunnelStage(1, "S1_IDENTITY_VALID", 1, 1, 0, 0, (), 1)
    fabricated = tuple(
        replace(stage, reason_counts=(("INVENTED_REASON", stage.input_count),))
        if stage.stage_id == "S1_IDENTITY_VALID"
        else stage
        for stage in funnel.stages
    )
    with pytest.raises(ValueError, match="exactly reconcile"):
        UniverseFunnel(funnel.evaluations, fabricated, funnel.members)


def test_funnel_is_an_aggregator_not_a_second_business_rule_owner() -> None:
    source = inspect.getsource(funnel_module)
    tree = ast.parse(source)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}

    assert not any(
        any(part.startswith("futu") or part == "streamlit" for part in module.lower().split("."))
        for module in imported_modules
    )
    assert not {"Decimal", "evaluate_security", "resolve_classification", "detect_flat_base"} & names
