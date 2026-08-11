from datetime import UTC, date, datetime, timedelta

import pytest

from tv_quant.pattern_finder import review
from tv_quant.pattern_finder.review import (
    COMPUTER_FILTERS,
    HUMAN_FILTERS,
    VALIDATION_FILTERS,
    attach_latest_validations,
    filter_review_rows,
)
from tv_quant.pattern_finder.validation import build_pattern_validation


RECORDED = datetime(2026, 8, 10, 4, 0, tzinfo=UTC)
SCAN_ROWS = (
    {"Symbol": "AAPL", "Flat Base": "YES", "Detector Version": "phase1-v1", "Base End": "2026-08-07"},
    {"Symbol": "MSFT", "Flat Base": "NO", "Detector Version": "phase1-v1", "Base End": "2026-08-07"},
    {"Symbol": "JPM", "Flat Base": "NO", "Detector Version": "phase1-v1", "Base End": "2026-08-07"},
    {"Symbol": "XOM", "Flat Base": "YES", "Detector Version": "phase1-v1", "Base End": "2026-08-07"},
)
DIAGNOSTICS = {
    "base_length": 25,
    "base_depth": 0.14,
    "bottom_tests": 2,
    "normalized_slope": 0.0,
    "support": 99.0,
    "resistance": 102.0,
}


def test_review_as_of_override_accepts_only_timezone_aware_utc() -> None:
    expected = datetime(2026, 8, 10, 4, 0, tzinfo=UTC)

    assert review.resolve_review_as_of_utc(expected.isoformat()) == expected
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        review.resolve_review_as_of_utc("2026-08-10T04:00:00")
    with pytest.raises(ValueError, match="timezone-aware UTC"):
        review.resolve_review_as_of_utc("2026-08-10T12:00:00+08:00")


def _record(row_index: int, label: str, reasons: tuple[str, ...], minute: int):
    return build_pattern_validation(
        recorded_at_utc=RECORDED + timedelta(minutes=minute),
        symbol=str(SCAN_ROWS[row_index]["Symbol"]),
        pattern_type="flat_base",
        detector_version="phase1-v1",
        scan_as_of_date=date(2026, 8, 7),
        computer_result=str(SCAN_ROWS[row_index]["Flat Base"]),
        human_label=label,
        reason_tags=reasons,
        note=f"note-{minute}",
        review_window_start=date(2026, 7, 6),
        review_window_end=date(2026, 8, 7),
        diagnostics=DIAGNOSTICS,
    )


HISTORY = (
    _record(0, "勉强像", ("波动区间过宽",), 1),
    _record(0, "像", (), 2),
    _record(1, "不像", ("整体仍明显向下",), 3),
    _record(2, "勉强像", ("整体仍明显向上",), 4),
)


def _enriched():
    return attach_latest_validations(
        SCAN_ROWS,
        HISTORY,
        pattern_type="flat_base",
        computer_result_field="Flat Base",
        scan_date_field="Base End",
    )


def test_attach_latest_isolated_by_pattern_and_exposes_result_label() -> None:
    rows = _enriched()
    by_symbol = {row["Symbol"]: row for row in rows}

    assert by_symbol["AAPL"]["Pattern Type"] == "flat_base"
    assert by_symbol["AAPL"]["Computer Result"] == "YES"
    assert by_symbol["AAPL"]["Scan As Of Date"] == "2026-08-07"
    assert by_symbol["AAPL"]["Human Label"] == "像"
    assert by_symbol["AAPL"]["Validation Result"] == "一致命中"
    assert by_symbol["AAPL"]["Validation History Count"] == 2
    assert by_symbol["XOM"]["Validation Result"] is None


@pytest.mark.parametrize(
    ("computer_filter", "human_filter", "validation_filter", "expected"),
    [
        ("全部", "全部", "全部", ("AAPL", "MSFT", "JPM", "XOM")),
        ("是", "全部", "全部", ("AAPL", "XOM")),
        ("否", "勉强像", "边界案例", ("JPM",)),
        ("全部", "未人工复核", "全部", ("XOM",)),
        ("全部", "不像", "一致排除", ("MSFT",)),
    ],
)
def test_three_filters_compose(
    computer_filter: str,
    human_filter: str,
    validation_filter: str,
    expected: tuple[str, ...],
) -> None:
    rows = filter_review_rows(
        _enriched(),
        computer_filter=computer_filter,
        human_filter=human_filter,
        validation_filter=validation_filter,
    )
    assert tuple(row["Symbol"] for row in rows) == expected


def test_filter_options_are_chinese_and_unknown_values_are_rejected() -> None:
    assert COMPUTER_FILTERS == ("全部", "是", "否")
    assert HUMAN_FILTERS == ("全部", "未人工复核", "像", "勉强像", "不像")
    assert VALIDATION_FILTERS == (
        "全部",
        "一致命中",
        "一致排除",
        "疑似误报",
        "疑似漏报",
        "边界案例",
    )
    with pytest.raises(ValueError, match="unknown computer filter"):
        filter_review_rows(
            (),
            computer_filter="YES",
            human_filter="全部",
            validation_filter="全部",
        )
