import json
from pathlib import Path

import pytest

from tv_quant.pattern_finder.validation import (
    PatternValidation,
    ValidationStoreError,
    migrate_legacy_validations,
    read_validation_history,
)


def _legacy_payload(recorded_at_utc: str, *, tag: str = "低点不稳定") -> dict[str, object]:
    return {
        "recorded_at_utc": recorded_at_utc,
        "symbol": "AAPL",
        "detector_version": "phase1-v1",
        "scan_as_of_date": "2026-08-07",
        "computer_flat_base": "YES",
        "base_length": 25,
        "base_depth": 0.1485,
        "bottom_tests": 2,
        "normalized_slope": -8.9e-06,
        "human_label": "不像",
        "reason_tags": [tag],
        "note": "legacy review",
    }


def _write_legacy(path: Path, payloads: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    legacy = tmp_path / "data/manual/flat_base_validation.jsonl"
    target = tmp_path / "data/manual/pattern_validation.jsonl"
    ledger = tmp_path / "data/manual/pattern_validation_migration_ledger.jsonl"
    return legacy, target, ledger


def test_migration_preserves_every_record_and_legacy_meaning(tmp_path: Path) -> None:
    legacy, target, ledger = _paths(tmp_path)
    payloads = [
        _legacy_payload("2026-08-10T04:00:00+00:00"),
        _legacy_payload("2026-08-10T04:05:00+00:00"),
    ]
    _write_legacy(legacy, payloads)
    source_bytes = legacy.read_bytes()

    summary = migrate_legacy_validations(
        legacy, target, ledger, repository_root=tmp_path
    )

    records = read_validation_history(target)
    assert summary.migrated == 2
    assert len(records) == 2
    assert all(isinstance(record, PatternValidation) for record in records)
    first = records[0]
    assert isinstance(first, PatternValidation)
    assert first.pattern_type == "flat_base"
    assert first.pattern_display_name == "平底形态"
    assert first.computer_result == "YES"
    assert first.validation_result == "possible_false_positive"
    assert first.reason_tags == ("低点不稳定",)
    assert first.review_window_start is None
    assert first.review_window_end is None
    assert first.diagnostics == {
        "base_length": 25,
        "base_depth": 0.1485,
        "bottom_tests": 2,
        "normalized_slope": -8.9e-06,
    }
    assert legacy.read_bytes() == source_bytes
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 2


def test_migration_is_idempotent_without_business_key_deduplication(
    tmp_path: Path,
) -> None:
    legacy, target, ledger = _paths(tmp_path)
    _write_legacy(
        legacy,
        [
            _legacy_payload("2026-08-10T04:00:00+00:00"),
            _legacy_payload("2026-08-10T04:05:00+00:00"),
        ],
    )
    migrate_legacy_validations(legacy, target, ledger, repository_root=tmp_path)

    summary = migrate_legacy_validations(
        legacy, target, ledger, repository_root=tmp_path
    )

    assert summary.migrated == 0
    assert summary.already_migrated == 2
    assert len(read_validation_history(target)) == 2


def test_migration_repairs_missing_ledger_from_target_provenance(tmp_path: Path) -> None:
    legacy, target, ledger = _paths(tmp_path)
    _write_legacy(legacy, [_legacy_payload("2026-08-10T04:00:00+00:00")])
    migrate_legacy_validations(legacy, target, ledger, repository_root=tmp_path)
    ledger.unlink()

    summary = migrate_legacy_validations(
        legacy, target, ledger, repository_root=tmp_path
    )

    assert summary.migrated == 0
    assert summary.ledger_repaired == 1
    assert len(read_validation_history(target)) == 1
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 1


def test_migration_only_imports_later_appended_source_lines(tmp_path: Path) -> None:
    legacy, target, ledger = _paths(tmp_path)
    _write_legacy(legacy, [_legacy_payload("2026-08-10T04:00:00+00:00")])
    migrate_legacy_validations(legacy, target, ledger, repository_root=tmp_path)
    with legacy.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                _legacy_payload("2026-08-10T04:05:00+00:00"),
                ensure_ascii=False,
            )
            + "\n"
        )

    summary = migrate_legacy_validations(
        legacy, target, ledger, repository_root=tmp_path
    )

    assert summary.migrated == 1
    assert summary.already_migrated == 1
    assert len(read_validation_history(target)) == 2


def test_migration_rejects_changed_content_at_an_already_seen_source_line(
    tmp_path: Path,
) -> None:
    legacy, target, ledger = _paths(tmp_path)
    _write_legacy(legacy, [_legacy_payload("2026-08-10T04:00:00+00:00")])
    migrate_legacy_validations(legacy, target, ledger, repository_root=tmp_path)
    original_target = target.read_bytes()
    _write_legacy(
        legacy,
        [_legacy_payload("2026-08-10T04:00:00+00:00", tag="整体仍在下降")],
    )

    with pytest.raises(ValidationStoreError, match="source line changed"):
        migrate_legacy_validations(legacy, target, ledger, repository_root=tmp_path)

    assert target.read_bytes() == original_target


def test_migration_rejects_malformed_legacy_json_with_line_number(
    tmp_path: Path,
) -> None:
    legacy, target, ledger = _paths(tmp_path)
    legacy.parent.mkdir(parents=True)
    legacy.write_text("not-json\n", encoding="utf-8")

    with pytest.raises(ValidationStoreError, match="line 1"):
        migrate_legacy_validations(legacy, target, ledger, repository_root=tmp_path)

    assert not target.exists()
