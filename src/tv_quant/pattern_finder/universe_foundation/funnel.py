"""Deterministic S0-S10 reconciliation of Task 6 security evaluations."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Sequence

from tv_quant.run_manifest import canonical_hash

from .evaluator import SecurityEvaluation
from .evidence import Decision


_STAGE_IDS = (
    "S0_DISCOVERED_US_CASH_SECURITIES",
    "S1_IDENTITY_VALID",
    "S2_EXCHANGE_ALLOWED",
    "S3_SECURITY_CLASS_ALLOWED",
    "S4_ACTIVE_STATUS_ALLOWED",
    "S5_PRICE_ALLOWED",
    "S6_MARKET_CAP_ALLOWED",
    "S7_SECTOR_INDUSTRY_ALLOWED",
    "S8_LISTING_HISTORY_ALLOWED",
    "S9_LIQUIDITY_ALLOWED",
    "S10_CORE_UNIVERSE",
)
_FIELD_STAGE_IDS = _STAGE_IDS[1:-1]


def _ordered_evaluations(values: Sequence[SecurityEvaluation]) -> tuple[SecurityEvaluation, ...]:
    evaluations = tuple(values)
    if not evaluations:
        raise ValueError("evaluations: non-empty SecurityEvaluation sequence required")
    if any(type(item) is not SecurityEvaluation for item in evaluations):
        raise ValueError("evaluations: SecurityEvaluation values required")
    keys = tuple((item.stock_id, item.futu_code) for item in evaluations)
    if len(set(keys)) != len(keys):
        raise ValueError("evaluations: duplicate evaluation key")
    codes = {item.futu_code: item.stock_id for item in evaluations}
    if len(codes) != len(evaluations):
        raise ValueError("UNIVERSE_IDENTITY_BLOCKER: futu_code maps to multiple stock_ids")
    by_stock_id: dict[str, list[SecurityEvaluation]] = {}
    for item in evaluations:
        by_stock_id.setdefault(item.stock_id, []).append(item)
    for same_stock_id in by_stock_id.values():
        if len(same_stock_id) > 1 and any(
            item.field_decisions[0].decision is not Decision.UNKNOWN
            or item.field_decisions[0].reason_code != "UNIVERSE_IDENTITY_BLOCKER"
            for item in same_stock_id
        ):
            raise ValueError("UNIVERSE_IDENTITY_BLOCKER: duplicate stock_id requires Task 6 identity blockers")
    return tuple(sorted(evaluations, key=lambda item: (item.stock_id, item.futu_code, item.symbol, item.name)))


@dataclass(frozen=True, slots=True)
class FunnelStage:
    """One reconciled stage in the immutable display order."""

    stage_order: int
    stage_id: str
    input_count: int
    pass_count: int
    fail_count: int
    unknown_count: int
    reason_counts: tuple[tuple[str, int], ...]
    output_count: int

    def __post_init__(self) -> None:
        if type(self.stage_order) is not int or self.stage_order < 0:
            raise ValueError("stage_order: non-negative integer required")
        if self.stage_id not in _STAGE_IDS:
            raise ValueError("stage_id: fixed S0-S10 stage required")
        for name in ("input_count", "pass_count", "fail_count", "unknown_count", "output_count"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{name}: non-negative integer required")
        if self.input_count != self.pass_count + self.fail_count + self.unknown_count:
            raise ValueError("input_count must reconcile to PASS + FAIL + UNKNOWN")
        if self.output_count != self.pass_count:
            raise ValueError("output_count must equal pass_count")
        reasons = tuple(self.reason_counts)
        if any(
            type(reason) is not str
            or not reason
            or type(count) is not int
            or count <= 0
            for reason, count in reasons
        ):
            raise ValueError("reason_counts: non-empty reason and positive count required")
        if reasons != tuple(sorted(reasons)) or len({reason for reason, _ in reasons}) != len(reasons):
            raise ValueError("reason_counts: sorted unique reason codes required")
        if self.stage_id in _FIELD_STAGE_IDS and sum(count for _, count in reasons) != self.input_count:
            raise ValueError("reason_counts must reconcile to field-stage input_count")
        if self.stage_id not in _FIELD_STAGE_IDS and reasons:
            raise ValueError("S0 and S10 reason_counts must be empty")
        object.__setattr__(self, "reason_counts", reasons)


@dataclass(frozen=True, slots=True)
class UniverseFunnel:
    """All supplied evaluations, their fixed-stage reconciliation, and final members."""

    evaluations: tuple[SecurityEvaluation, ...]
    stages: tuple[FunnelStage, ...]
    members: tuple[SecurityEvaluation, ...]

    def __post_init__(self) -> None:
        evaluations = _ordered_evaluations(self.evaluations)
        stages = tuple(self.stages)
        members = tuple(self.members)
        if tuple(stage.stage_id for stage in stages) != _STAGE_IDS:
            raise ValueError("stages: fixed S0-S10 order required")
        if any(type(stage) is not FunnelStage for stage in stages):
            raise ValueError("stages: FunnelStage values required")
        if any(stage.stage_order != index for index, stage in enumerate(stages)):
            raise ValueError("stages: fixed stage order required")
        expected_stages, expected_members = _reconcile(evaluations)
        if stages != expected_stages:
            raise ValueError("stages must exactly reconcile supplied Task 6 evaluations")
        if members != expected_members:
            raise ValueError("members must equal Task 6 final members")
        object.__setattr__(self, "evaluations", evaluations)
        object.__setattr__(self, "stages", stages)
        object.__setattr__(self, "members", members)


def _stage(
    stage_order: int,
    stage_id: str,
    candidates: tuple[SecurityEvaluation, ...],
    decision_index: int,
) -> tuple[FunnelStage, tuple[SecurityEvaluation, ...]]:
    decisions = tuple((item, item.field_decisions[decision_index]) for item in candidates)
    passers = tuple(item for item, decision in decisions if decision.decision is Decision.PASS)
    reason_counts = tuple(sorted(Counter(decision.reason_code for _, decision in decisions).items()))
    return (
        FunnelStage(
            stage_order=stage_order,
            stage_id=stage_id,
            input_count=len(candidates),
            pass_count=len(passers),
            fail_count=sum(decision.decision is Decision.FAIL for _, decision in decisions),
            unknown_count=sum(decision.decision is Decision.UNKNOWN for _, decision in decisions),
            reason_counts=reason_counts,
            output_count=len(passers),
        ),
        passers,
    )


def _reconcile(
    evaluations: tuple[SecurityEvaluation, ...],
) -> tuple[tuple[FunnelStage, ...], tuple[SecurityEvaluation, ...]]:
    stages: list[FunnelStage] = [
        FunnelStage(0, _STAGE_IDS[0], len(evaluations), len(evaluations), 0, 0, (), len(evaluations))
    ]
    candidates = evaluations
    for index, stage_id in enumerate(_FIELD_STAGE_IDS):
        stage, candidates = _stage(index + 1, stage_id, candidates, index)
        stages.append(stage)
    stages.append(
        FunnelStage(10, _STAGE_IDS[-1], len(candidates), len(candidates), 0, 0, (), len(candidates))
    )
    return tuple(stages), candidates


def build_funnel(evaluations: Sequence[SecurityEvaluation]) -> UniverseFunnel:
    """Aggregate existing Task 6 decisions without re-evaluating any business rule."""

    ordered = _ordered_evaluations(evaluations)
    stages, members = _reconcile(ordered)
    return UniverseFunnel(ordered, stages, members)


def _audit_value(value: object) -> dict[str, str]:
    return {
        "type": f"{type(value).__module__}.{type(value).__qualname__}",
        "representation": repr(value),
    }


def funnel_sha256(funnel: UniverseFunnel) -> str:
    """Hash the complete, deterministic funnel aggregation using the shared canonical owner."""

    if type(funnel) is not UniverseFunnel:
        raise ValueError("UniverseFunnel required")
    return canonical_hash(
        {
            "evaluations": [
                {
                    "stock_id": item.stock_id,
                    "futu_code": item.futu_code,
                    "symbol": item.symbol,
                    "name": item.name,
                    "first_exit_stage": item.first_exit_stage,
                    "first_exit_reason_code": item.first_exit_reason_code,
                    "is_member": item.is_member,
                    "is_quarantined": item.is_quarantined,
                    "field_decisions": [
                        {
                            "field_id": decision.field_id,
                            "raw_value": _audit_value(decision.raw_value),
                            "normalized_value": _audit_value(decision.normalized_value),
                            "operator": decision.operator,
                            "threshold": _audit_value(decision.threshold),
                            "decision": decision.decision.value,
                            "reason_code": decision.reason_code,
                            "evidence_source": decision.evidence_source,
                            "evidence_observed_at_utc": _audit_value(decision.evidence_observed_at_utc),
                            "evidence_version": decision.evidence_version,
                            "evidence_references": [
                                {
                                    "source_id": reference.source_id,
                                    "source_locator": reference.source_locator,
                                    "source_record_sha256": reference.source_record_sha256,
                                }
                                for reference in decision.evidence_references
                            ],
                        }
                        for decision in item.field_decisions
                    ],
                }
                for item in funnel.evaluations
            ],
            "stages": [
                {
                    "stage_order": stage.stage_order,
                    "stage_id": stage.stage_id,
                    "input_count": stage.input_count,
                    "pass_count": stage.pass_count,
                    "fail_count": stage.fail_count,
                    "unknown_count": stage.unknown_count,
                    "reason_counts": [[reason, count] for reason, count in stage.reason_counts],
                    "output_count": stage.output_count,
                }
                for stage in funnel.stages
            ],
            "members": [
                {"stock_id": item.stock_id, "futu_code": item.futu_code}
                for item in funnel.members
            ],
        }
    )


__all__ = ("FunnelStage", "UniverseFunnel", "build_funnel", "funnel_sha256")
