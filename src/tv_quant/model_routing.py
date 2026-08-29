"""Deterministic Codex model recommendations for project work."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    model: str
    reasoning_effort: str
    complexity_score: int
    reasons: tuple[str, ...]
    hard_floor: str | None
    escalate_when: tuple[str, ...]


def recommend_model(
    task_text: str,
    changed_paths: Iterable[str] = (),
) -> RoutingDecision:
    """Recommend the lowest capable profile from explicit project signals."""
    task = task_text.strip().lower()
    if not task:
        raise ValueError("task_text must be non-empty")

    paths = tuple(
        path.strip().replace("\\", "/").lower()
        for path in changed_paths
        if path.strip()
    )
    evidence = " ".join((task, *paths))
    score = 5
    reasons: list[str] = ["base task scope"]
    hard_floor: str | None = None

    if _contains(evidence, "api", "opend", "futu", "network", "integration"):
        score += 40
        reasons.append("external integration")
    if _contains(evidence, "debug", "bug", "root cause", "regression"):
        score += 15
        reasons.append("diagnosis or regression work")
    if _contains(evidence, "public interface", "contract", "interface"):
        score += 15
        reasons.append("public interface impact")
    if _contains(evidence, "redesign", "architecture", "refactor", "unknown"):
        score += 25
        reasons.append("high uncertainty or architecture change")

    unique_paths = tuple(dict.fromkeys(paths))
    if len(unique_paths) > 1:
        score += min(20, (len(unique_paths) - 1) * 5)
        reasons.append(f"{len(unique_paths)} changed-path signals")

    if _contains(
        evidence,
        "migration",
        "migrate",
        "schema",
        "transaction",
        "persistence",
        "/persistence/",
    ):
        score = max(score, 90)
        hard_floor = "SOL_XHIGH"
        reasons.append("persistent-state integrity risk")
    elif _contains(
        evidence,
        "credential",
        "secret",
        "security",
        "broker",
        "order",
        "pnl",
        "money",
    ):
        score = max(score, 75)
        hard_floor = "TERRA_XHIGH"
        reasons.append("security or trading-domain risk")

    bounded_score = min(score, 100)
    model, reasoning_effort = _profile_for(bounded_score, hard_floor)
    return RoutingDecision(
        model=model,
        reasoning_effort=reasoning_effort,
        complexity_score=bounded_score,
        reasons=tuple(reasons),
        hard_floor=hard_floor,
        escalate_when=(
            "测试连续两次无法定位失败原因",
            "实际修改范围超出已评估路径",
            "发现持久化、安全或真实交易边界",
        ),
    )


def _contains(evidence: str, *terms: str) -> bool:
    return any(term in evidence for term in terms)


def _profile_for(score: int, hard_floor: str | None) -> tuple[str, str]:
    if hard_floor == "SOL_XHIGH" or score >= 90:
        return "gpt-5.6-sol", "xhigh"
    if hard_floor == "TERRA_XHIGH" or score >= 75:
        return "gpt-5.6-terra", "xhigh"
    if score >= 60:
        return "gpt-5.6-terra", "high"
    if score >= 40:
        return "gpt-5.6-terra", "medium"
    if score >= 20:
        return "gpt-5.6-luna", "medium"
    return "gpt-5.6-luna", "low"
