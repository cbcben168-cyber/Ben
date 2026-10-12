from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

from .contracts import FAMILY, Phase4ContractError
from .mechanisms import Signal


@dataclass(frozen=True)
class OverlapResult:
    hypothesis_a: str
    hypothesis_b: str
    n_a: int
    n_b: int
    matched: int
    jaccard: float | None
    status: str


def _validate_unique(signals: list[Signal]) -> None:
    identities = [(s.hypothesis_id, s.session_date) for s in signals]
    if len(identities) != len(set(identities)):
        raise Phase4ContractError("DUPLICATE_DAILY_SIGNAL_ENTITLEMENT")


def pair_overlap(signals_a: Iterable[Signal], signals_b: Iterable[Signal]) -> OverlapResult:
    left = sorted(list(signals_a), key=lambda s: (s.session_date, s.bar_in_session))
    right = sorted(list(signals_b), key=lambda s: (s.session_date, s.bar_in_session))
    _validate_unique(left)
    _validate_unique(right)
    name_a = left[0].hypothesis_id if left else "EMPTY_A"
    name_b = right[0].hypothesis_id if right else "EMPTY_B"
    right_by_date = {s.session_date: s for s in right}
    matched = sum(
        1
        for signal in left
        if (other := right_by_date.get(signal.session_date)) is not None
        and other.direction == signal.direction
        and abs(other.bar_in_session - signal.bar_in_session) <= 1
    )
    union = len(left) + len(right) - matched
    if union == 0:
        return OverlapResult(name_a, name_b, 0, 0, 0, None, "OVERLAP_NOT_COMPUTABLE")
    jaccard = matched / union
    status = "HIGH_OVERLAP" if jaccard >= 0.80 else "PASS"
    return OverlapResult(name_a, name_b, len(left), len(right), matched, jaccard, status)


def family_overlap(signals: Iterable[Signal]) -> list[OverlapResult]:
    all_signals = list(signals)
    if set(s.hypothesis_id for s in all_signals).difference(FAMILY):
        raise Phase4ContractError("UNREGISTERED_HYPOTHESIS")
    _validate_unique(all_signals)
    by_hypothesis = {name: [s for s in all_signals if s.hypothesis_id == name] for name in FAMILY}
    results: list[OverlapResult] = []
    for name_a, name_b in combinations(FAMILY, 2):
        result = pair_overlap(by_hypothesis[name_a], by_hypothesis[name_b])
        results.append(
            OverlapResult(name_a, name_b, result.n_a, result.n_b, result.matched, result.jaccard, result.status)
        )
    return results


def overlap_gate(results: Iterable[OverlapResult]) -> str:
    return "BLOCKED_HIGH_OVERLAP" if any(r.status == "HIGH_OVERLAP" for r in results) else "PASS"
