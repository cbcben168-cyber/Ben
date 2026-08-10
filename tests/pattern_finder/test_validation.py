import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from tv_quant.pattern_finder.validation import (
    FlatBaseValidation,
    PatternValidation,
    ValidationStoreError,
    append_validation,
    build_validation,
    latest_validations,
    read_validation_history,
)


SCAN_ROW = {
    "Symbol": "AAPL",
    "Detector Version": "phase1-v1",
    "Flat Base": "YES",
    "Base Length": 25,
    "Base Depth": 0.14856633333333338,
    "Bottom Tests": 2,
    "Normalized Slope": -8.925200977341337e-06,
}
RECORDED_1 = datetime(2026, 8, 10, 4, 0, tzinfo=UTC)
RECORDED_2 = RECORDED_1 + timedelta(minutes=5)


def test_pattern_validation_round_trips_generic_schema() -> None:
    record = PatternValidation(
        recorded_at_utc=RECORDED_1,
        symbol="AAPL",
        pattern_type="flat_base",
        pattern_display_name="平底形态",
        detector_version="phase1-v1",
        scan_as_of_date="2026-08-07",
        computer_result="YES",
        human_label="像",
        validation_result="true_positive_like",
        reason_tags=(),
        note="",
        review_window_start="2026-07-06",
        review_window_end="2026-08-07",
        diagnostics={
            "base_length": 25,
            "base_depth": 0.14,
            "bottom_tests": 2,
            "normalized_slope": 0.0,
            "support": 99.0,
            "resistance": 102.0,
        },
        migration_provenance=None,
    )

    assert record.key == ("AAPL", "flat_base", "phase1-v1", "2026-08-07")
    assert PatternValidation.from_dict(record.to_dict()) == record


def test_new_pattern_validation_requires_complete_review_window() -> None:
    with pytest.raises(ValueError, match="review window"):
        PatternValidation(
            recorded_at_utc=RECORDED_1,
            symbol="AAPL",
            pattern_type="flat_base",
            pattern_display_name="平底形态",
            detector_version="phase1-v1",
            scan_as_of_date="2026-08-07",
            computer_result="YES",
            human_label="像",
            validation_result="true_positive_like",
            reason_tags=(),
            note="",
            review_window_start=None,
            review_window_end=None,
            diagnostics={},
            migration_provenance=None,
        )


def test_validation_appends_history_and_selects_latest_record(tmp_path: Path) -> None:
    path = tmp_path / "flat_base_validation.jsonl"
    first = build_validation(
        SCAN_ROW,
        date(2026, 8, 7),
        "勉强像",
        ("宽幅震荡",),
        "first",
        RECORDED_1,
    )
    second = build_validation(
        SCAN_ROW,
        date(2026, 8, 7),
        "不像",
        ("整体仍在下降",),
        "second",
        RECORDED_2,
    )

    append_validation(path, first)
    append_validation(path, second)

    history = read_validation_history(path)
    assert history == (first, second)
    assert latest_validations(history)[
        ("AAPL", "phase1-v1", "2026-08-07")
    ] == second
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.parametrize("label", ["像", "勉强像", "不像"])
def test_only_three_human_labels_are_accepted(label: str) -> None:
    record = build_validation(
        SCAN_ROW,
        date(2026, 8, 7),
        label,
        (),
        "",
        RECORDED_1,
    )
    assert record.human_label == label

    with pytest.raises(ValueError, match="human_label"):
        build_validation(
            SCAN_ROW,
            date(2026, 8, 7),
            "很像",
            (),
            "",
            RECORDED_1,
        )


def test_label_and_reason_combinations_are_strict() -> None:
    with pytest.raises(ValueError, match="像.*原因"):
        build_validation(
            SCAN_ROW,
            date(2026, 8, 7),
            "像",
            ("底部太深",),
            "",
            RECORDED_1,
        )
    with pytest.raises(ValueError, match="未知原因"):
        build_validation(
            SCAN_ROW,
            date(2026, 8, 7),
            "不像",
            ("参数需要优化",),
            "",
            RECORDED_1,
        )


def test_build_validation_requires_literal_detector_diagnostics() -> None:
    for missing in (
        "Symbol",
        "Detector Version",
        "Flat Base",
        "Base Length",
        "Base Depth",
        "Bottom Tests",
        "Normalized Slope",
    ):
        row = dict(SCAN_ROW)
        row.pop(missing)
        with pytest.raises(ValueError, match=missing):
            build_validation(
                row,
                date(2026, 8, 7),
                "像",
                (),
                "",
                RECORDED_1,
            )


def test_validation_normalizes_note_and_rejects_invalid_metadata() -> None:
    record = build_validation(
        SCAN_ROW,
        date(2026, 8, 7),
        "不像",
        ("其他", "其他"),
        "  short note  ",
        RECORDED_1,
    )
    assert record.note == "short note"
    assert record.reason_tags == ("其他",)
    assert record.computer_flat_base == "YES"

    with pytest.raises(ValueError, match="280"):
        build_validation(
            SCAN_ROW,
            date(2026, 8, 7),
            "像",
            (),
            "x" * 281,
            RECORDED_1,
        )
    with pytest.raises(ValueError, match="UTC"):
        build_validation(
            SCAN_ROW,
            date(2026, 8, 7),
            "像",
            (),
            "",
            datetime(2026, 8, 10, 4, 0),
        )
    wrong_version = {**SCAN_ROW, "Detector Version": "phase1-v2"}
    with pytest.raises(ValueError, match="phase1-v1"):
        build_validation(
            wrong_version,
            date(2026, 8, 7),
            "像",
            (),
            "",
            RECORDED_1,
        )


def test_history_reader_handles_missing_and_rejects_corrupt_lines(tmp_path: Path) -> None:
    path = tmp_path / "flat_base_validation.jsonl"
    assert read_validation_history(path) == ()

    valid = build_validation(
        SCAN_ROW,
        date(2026, 8, 7),
        "像",
        (),
        "",
        RECORDED_1,
    )
    path.write_text(
        json.dumps(valid.to_dict(), ensure_ascii=False) + "\nnot-json\n",
        encoding="utf-8",
    )
    with pytest.raises(ValidationStoreError, match="line 2"):
        read_validation_history(path)


def test_validation_record_round_trips_json_fields() -> None:
    record = build_validation(
        SCAN_ROW,
        date(2026, 8, 7),
        "勉强像",
        ("低点不稳定", "阻力不清楚"),
        "check again",
        RECORDED_1,
    )
    assert FlatBaseValidation.from_dict(record.to_dict()) == record
