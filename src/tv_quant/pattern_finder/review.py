from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping

from .validation import FlatBaseValidation, latest_validations


SCAN_FILTERS = (
    "全部",
    "Flat Base YES",
    "Flat Base NO",
    "未人工验证",
    "像",
    "勉强像",
    "不像",
)


def _row_key(row: Mapping[str, object]) -> tuple[str, str, str] | None:
    symbol = row.get("Symbol")
    detector_version = row.get("Detector Version")
    scan_as_of_date = row.get("Base End")
    if symbol is None or detector_version is None or scan_as_of_date is None:
        return None
    return (str(symbol), str(detector_version), str(scan_as_of_date))


def attach_latest_validations(
    rows: Iterable[Mapping[str, object]],
    history: Iterable[FlatBaseValidation],
) -> tuple[dict[str, object], ...]:
    records = tuple(history)
    latest = latest_validations(records)
    counts = Counter(record.key for record in records)
    enriched: list[dict[str, object]] = []
    for row in rows:
        key = _row_key(row)
        record = latest.get(key) if key is not None else None
        enriched.append(
            {
                **row,
                "Human Label": record.human_label if record else None,
                "Reason Tags": record.reason_tags if record else (),
                "Human Note": record.note if record else "",
                "Validation History Count": counts[key] if key is not None else 0,
            }
        )
    return tuple(enriched)


def filter_review_rows(
    rows: Iterable[Mapping[str, object]],
    selected_filter: str,
) -> tuple[dict[str, object], ...]:
    if selected_filter not in SCAN_FILTERS:
        raise ValueError(f"unknown review filter: {selected_filter}")
    materialized = tuple(dict(row) for row in rows)
    if selected_filter == "全部":
        return materialized
    if selected_filter == "Flat Base YES":
        return tuple(row for row in materialized if row.get("Flat Base") == "YES")
    if selected_filter == "Flat Base NO":
        return tuple(row for row in materialized if row.get("Flat Base") == "NO")
    if selected_filter == "未人工验证":
        return tuple(row for row in materialized if row.get("Human Label") is None)
    return tuple(
        row for row in materialized if row.get("Human Label") == selected_filter
    )
