from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from .flat_base import FlatBaseResult
from .validation import (
    PatternValidation,
    VALIDATION_RESULT_LABELS,
    latest_validations,
)


COMPUTER_FILTERS = ("全部", "是", "否")
HUMAN_FILTERS = ("全部", "未人工复核", "像", "勉强像", "不像")
VALIDATION_FILTERS = (
    "全部",
    "一致命中",
    "一致排除",
    "疑似误报",
    "疑似漏报",
    "边界案例",
)


@dataclass(frozen=True, slots=True)
class PatternReviewInput:
    computer_result: str
    detector_version: str
    scan_as_of_date: date
    review_window_start: date
    review_window_end: date
    diagnostics: dict[str, int | float]


def flat_base_review_input(result: FlatBaseResult) -> PatternReviewInput:
    selected = result.selected
    return PatternReviewInput(
        computer_result="YES" if result.pattern_flat_base else "NO",
        detector_version=result.detector_version,
        scan_as_of_date=selected.base_end.date(),
        review_window_start=selected.base_start.date(),
        review_window_end=selected.base_end.date(),
        diagnostics={
            "base_length": selected.base_length,
            "base_depth": selected.base_depth_pct,
            "bottom_tests": selected.bottom_test_count,
            "normalized_slope": selected.normalized_slope,
            "support": selected.support_level,
            "resistance": selected.resistance_level,
        },
    )


def _row_key(
    row: Mapping[str, object],
    *,
    pattern_type: str,
    scan_date_field: str,
) -> tuple[str, str, str, str] | None:
    symbol = row.get("Symbol")
    detector_version = row.get("Detector Version")
    scan_as_of_date = row.get(scan_date_field)
    if symbol is None or detector_version is None or scan_as_of_date is None:
        return None
    return (
        str(symbol),
        pattern_type,
        str(detector_version),
        str(scan_as_of_date),
    )


def attach_latest_validations(
    rows: Iterable[Mapping[str, object]],
    history: Iterable[PatternValidation],
    *,
    pattern_type: str,
    computer_result_field: str,
    scan_date_field: str,
) -> tuple[dict[str, object], ...]:
    records = tuple(record for record in history if record.pattern_type == pattern_type)
    latest = latest_validations(records)
    counts = Counter(record.key for record in records)
    enriched: list[dict[str, object]] = []
    for row in rows:
        key = _row_key(row, pattern_type=pattern_type, scan_date_field=scan_date_field)
        record = latest.get(key) if key is not None else None
        computer_result = row.get(computer_result_field)
        scan_as_of_date = row.get(scan_date_field)
        enriched.append(
            {
                **row,
                "Pattern Type": pattern_type,
                "Computer Result": computer_result,
                "Scan As Of Date": scan_as_of_date,
                "Human Label": record.human_label if record else None,
                "Reason Tags": record.reason_tags if record else (),
                "Human Note": record.note if record else "",
                "Validation Result": (
                    VALIDATION_RESULT_LABELS[record.validation_result]
                    if record
                    else None
                ),
                "Validation History Count": counts[key] if key is not None else 0,
            }
        )
    return tuple(enriched)


def filter_review_rows(
    rows: Iterable[Mapping[str, object]],
    *,
    computer_filter: str,
    human_filter: str,
    validation_filter: str,
) -> tuple[dict[str, object], ...]:
    if computer_filter not in COMPUTER_FILTERS:
        raise ValueError(f"unknown computer filter: {computer_filter}")
    if human_filter not in HUMAN_FILTERS:
        raise ValueError(f"unknown human filter: {human_filter}")
    if validation_filter not in VALIDATION_FILTERS:
        raise ValueError(f"unknown validation filter: {validation_filter}")

    materialized = tuple(dict(row) for row in rows)
    if computer_filter != "全部":
        expected = "YES" if computer_filter == "是" else "NO"
        materialized = tuple(
            row for row in materialized if row.get("Computer Result") == expected
        )
    if human_filter == "未人工复核":
        materialized = tuple(
            row for row in materialized if row.get("Human Label") is None
        )
    elif human_filter != "全部":
        materialized = tuple(
            row for row in materialized if row.get("Human Label") == human_filter
        )
    if validation_filter != "全部":
        materialized = tuple(
            row
            for row in materialized
            if row.get("Validation Result") == validation_filter
        )
    return materialized
