from __future__ import annotations

import pytest

from factor_research.phase4_mechanism_study.contracts import Phase4ContractError
from factor_research.phase4_mechanism_study.mechanisms import Signal
from factor_research.phase4_mechanism_study.overlap import family_overlap, overlap_gate, pair_overlap


def _signal(hypothesis: str, day: str, position: int, direction: int = 1) -> Signal:
    return Signal(hypothesis, day, position, position, "10:00", direction, 99.0, "FIXED_PRICE", 101.0, 6, {})


def test_overlap_is_deterministic_one_to_one_jaccard_with_inclusive_boundary() -> None:
    left = [_signal("P4_M01_ALL", "2025-10-01", 10), _signal("P4_M01_ALL", "2025-10-02", 20)]
    right = [_signal("P4_M02_ALL", "2025-10-01", 11), _signal("P4_M02_ALL", "2025-10-03", 20)]
    result = pair_overlap(left, right)
    assert result.matched == 1
    assert result.jaccard == pytest.approx(1 / 3)
    assert result.status == "PASS"


def test_overlap_includes_canceled_signal_identity_and_blocks_high_overlap() -> None:
    signals = []
    for index in range(5):
        day = f"2025-10-{index + 1:02d}"
        signals.extend([_signal("P4_M01_ALL", day, 10), _signal("P4_M02_ALL", day, 10)])
    results = family_overlap(signals)
    assert results[0].jaccard == 1.0
    assert overlap_gate(results) == "BLOCKED_HIGH_OVERLAP"


def test_empty_union_is_not_computable_and_daily_duplicate_is_rejected() -> None:
    assert pair_overlap([], []).status == "OVERLAP_NOT_COMPUTABLE"
    duplicate = [_signal("P4_M01_ALL", "2025-10-01", 10), _signal("P4_M01_ALL", "2025-10-01", 20)]
    with pytest.raises(Phase4ContractError, match="DUPLICATE_DAILY_SIGNAL_ENTITLEMENT"):
        family_overlap(duplicate)
