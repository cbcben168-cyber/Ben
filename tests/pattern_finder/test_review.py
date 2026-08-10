from datetime import UTC, date, datetime, timedelta

import pytest

from tv_quant.pattern_finder.review import (
    SCAN_FILTERS,
    attach_latest_validations,
    filter_review_rows,
)
from tv_quant.pattern_finder.validation import build_validation


RECORDED = datetime(2026, 8, 10, 4, 0, tzinfo=UTC)
SCAN_ROWS = (
    {
        "Symbol": "AAPL",
        "Flat Base": "YES",
        "Detector Version": "phase1-v1",
        "Base End": "2026-08-07",
        "Base Length": 25,
        "Base Depth": 0.14,
        "Bottom Tests": 2,
        "Normalized Slope": -0.00001,
    },
    {
        "Symbol": "MSFT",
        "Flat Base": "NO",
        "Detector Version": "phase1-v1",
        "Base End": "2026-08-07",
        "Base Length": 27,
        "Base Depth": 0.35,
        "Bottom Tests": 3,
        "Normalized Slope": 0.0102,
    },
    {
        "Symbol": "JPM",
        "Flat Base": "NO",
        "Detector Version": "phase1-v1",
        "Base End": "2026-08-07",
        "Base Length": 34,
        "Base Depth": 0.12,
        "Bottom Tests": 4,
        "Normalized Slope": 0.0028,
    },
    {
        "Symbol": "XOM",
        "Flat Base": "YES",
        "Detector Version": "phase1-v1",
        "Base End": "2026-08-07",
        "Base Length": 53,
        "Base Depth": 0.17,
        "Bottom Tests": 5,
        "Normalized Slope": 0.0008,
    },
)


def _record(
    row_index: int,
    label: str,
    reasons: tuple[str, ...],
    minute: int,
):
    return build_validation(
        SCAN_ROWS[row_index],
        date(2026, 8, 7),
        label,
        reasons,
        f"note-{minute}",
        RECORDED + timedelta(minutes=minute),
    )


HISTORY = (
    _record(0, "勉强像", ("宽幅震荡",), 1),
    _record(0, "像", (), 2),
    _record(1, "不像", ("整体仍在下降",), 3),
    _record(2, "勉强像", ("整体斜率太大",), 4),
)


def test_attach_latest_validation_preserves_history_count_and_latest_value() -> None:
    rows = attach_latest_validations(SCAN_ROWS, HISTORY)
    by_symbol = {row["Symbol"]: row for row in rows}

    assert by_symbol["AAPL"]["Human Label"] == "像"
    assert by_symbol["AAPL"]["Reason Tags"] == ()
    assert by_symbol["AAPL"]["Human Note"] == "note-2"
    assert by_symbol["AAPL"]["Validation History Count"] == 2
    assert by_symbol["XOM"]["Human Label"] is None
    assert by_symbol["XOM"]["Reason Tags"] == ()
    assert by_symbol["XOM"]["Validation History Count"] == 0


@pytest.mark.parametrize(
    ("selected_filter", "expected"),
    [
        ("全部", ("AAPL", "MSFT", "JPM", "XOM")),
        ("Flat Base YES", ("AAPL", "XOM")),
        ("Flat Base NO", ("MSFT", "JPM")),
        ("未人工验证", ("XOM",)),
        ("像", ("AAPL",)),
        ("勉强像", ("JPM",)),
        ("不像", ("MSFT",)),
    ],
)
def test_review_filter_supports_all_required_states(
    selected_filter: str,
    expected: tuple[str, ...],
) -> None:
    rows = attach_latest_validations(SCAN_ROWS, HISTORY)

    assert tuple(
        row["Symbol"] for row in filter_review_rows(rows, selected_filter)
    ) == expected


def test_review_filter_rejects_unknown_values() -> None:
    assert SCAN_FILTERS == (
        "全部",
        "Flat Base YES",
        "Flat Base NO",
        "未人工验证",
        "像",
        "勉强像",
        "不像",
    )
    with pytest.raises(ValueError, match="unknown review filter"):
        filter_review_rows((), "Human Score 5")
